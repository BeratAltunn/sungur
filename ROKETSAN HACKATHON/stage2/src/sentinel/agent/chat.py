"""Chat: a bounded tool-calling loop (≤ max_steps LLM calls) with grounding on the final answer.

The LLM decides which read-only tool to call; tools compute, the LLM phrases. Every number in the
answer must appear in this turn's tool outputs or the conversation so far; otherwise the LLM gets one
correction round, and a still-ungrounded answer is returned flagged (never silently).
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, Field

from sentinel.agent import grounding
from sentinel.agent.budget import BudgetExceeded
from sentinel.agent.llm import LLMClient, LLMError
from sentinel.agent.suggest import Suggestion
from sentinel.agent.tools import TOOL_SPECS, ChatTools, ToolError
from sentinel.observability.trace import Tracer

PROMPT_FILE = "chat_v2"


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    duration_ms: float = 0.0
    error: str | None = None


class ChatTurn(BaseModel):
    answer: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    grounded: bool = True
    unverified: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    duration_ms: float = 0.0
    note: str | None = None
    followups: list[Suggestion] = Field(default_factory=list)  # next questions, filled by the service


def _summary(out: Any) -> str:
    if isinstance(out, list):
        return f"{len(out)} kayıt"
    if isinstance(out, dict):
        for key in ("toplam", "toplam_tespit"):
            if key in out:
                return f"{key.replace('_', ' ')}: {out[key]}"
        if "zaman_cizelgesi" in out:
            return f"{len(out['zaman_cizelgesi'])} zaman noktası"
        if "araclar" in out:
            return f"{len(out['araclar'])} araç, {len(out.get('raporlar', []))} rapor"
    return "tamam"


class ChatAgent:
    def __init__(
        self,
        llm: LLMClient | None,
        tools: ChatTools,
        system_prompt: str,
        max_steps: int = 6,
        history_limit: int = 8,
    ):
        self.llm = llm
        self.tools = tools
        self.system = system_prompt
        self.max_steps = max_steps
        self.history_limit = history_limit

    def ask(
        self,
        question: str,
        history: list[ChatMessage] | None = None,
        image_id: str | None = None,
        tracer: Tracer | None = None,
        focus: str | None = None,
        context: str | None = None,
    ) -> ChatTurn:
        """`focus`: the vehicle the operator dragged into the chat, e.g. "V7 · T0122" (ids only, no numbers).
        `context`: several items put together, e.g. "V7 · T0122 (img_000860); img_006673"."""
        t0 = time.perf_counter()
        tracer = tracer or Tracer(None, "chat")
        if self.llm is None:
            return ChatTurn(
                answer="Sohbet için LLM bağlı değil. Kare ekranlarındaki kanıtlar ve brief'ler kullanılabilir.",
                grounded=True,
                note="llm_yok",
            )

        history = (history or [])[-self.history_limit :]
        user = question
        if context:
            user = f"[Bağlam: {context}]\n{user}"
        if focus:
            user = f"[Odak araç: {focus}]\n{user}"
        if image_id:
            user = f"[Açık kare: {image_id}]\n{user}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system}]
        messages += [
            {"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")
        ]
        messages.append({"role": "user", "content": user})

        outputs: list[Any] = []
        records: list[ToolCallRecord] = []
        conversation_texts = [m.content for m in history] + [user]
        corrected = False
        calls = 0

        for step in range(self.max_steps):
            last = step == self.max_steps - 1
            with tracer.step("sohbet_llm", {"adım": step + 1, "araçlar": not last}) as st:
                try:
                    resp = self.llm.chat(messages, tools=None if last else TOOL_SPECS)
                except (LLMError, BudgetExceeded) as e:
                    st["error"] = str(e)
                    return self._done(
                        t0,
                        calls,
                        records,
                        f"LLM'e şu an ulaşılamıyor ({e}). Lütfen tekrar deneyin.",
                        False,
                        [],
                        "llm_hata",
                    )
                calls += 1
                st["llm"] = {
                    "model": resp.model,
                    "tokens_in": resp.tokens_in,
                    "tokens_out": resp.tokens_out,
                    "cached": resp.cached,
                }

            if resp.tool_calls and not last:
                messages.append(
                    {
                        "role": "assistant",
                        "content": resp.content or "",
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {"name": c["name"], "arguments": c["arguments"]},
                            }
                            for c in resp.tool_calls
                        ],
                    }
                )
                for c in resp.tool_calls:
                    rec, out = self._run_tool(c, tracer)
                    records.append(rec)
                    if out is not None:
                        outputs.append(out)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": json.dumps(
                                out if out is not None else {"hata": rec.error}, ensure_ascii=False
                            ),
                        }
                    )
                continue

            answer = (resp.content or "").strip()
            if not answer:
                messages.append({"role": "user", "content": "Lütfen soruyu kısa bir cevapla yanıtla."})
                continue
            bank = grounding.EvidenceBank.from_sources(outputs, conversation_texts)
            g = grounding.check_text(answer, bank)
            if g.passed:
                return self._done(t0, calls, records, answer, True, [])
            if not corrected and not last:
                corrected = True
                messages.append({"role": "assistant", "content": answer})
                messages.append(
                    {
                        "role": "user",
                        "content": "Cevabında araç çıktılarında olmayan değerler var: "
                        + "; ".join((g.failed + g.unknown_refs)[:8])
                        + ". Yalnızca araç çıktılarındaki değerleri kullanarak cevabı yeniden yaz; gerekirse araç çağır.",
                    }
                )
                continue
            return self._done(
                t0,
                calls,
                records,
                answer,
                False,
                g.failed + g.unknown_refs,
                "Bazı değerler kanıtla doğrulanamadı; işaretli kısımları teyit edin.",
            )

        return self._done(
            t0,
            calls,
            records,
            "Bu soruyu adım sınırı içinde cevaplayamadım; soruyu daraltmayı deneyin.",
            True,
            [],
            "adim_siniri",
        )

    def _run_tool(self, call: dict, tracer: Tracer) -> tuple[ToolCallRecord, Any]:
        t = time.perf_counter()
        try:
            args = json.loads(call.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        rec = ToolCallRecord(name=call["name"], arguments=args if isinstance(args, dict) else {})
        with tracer.step(f"araç:{call['name']}", rec.arguments) as st:
            try:
                out = self.tools.call(call["name"], rec.arguments)
                rec.summary = _summary(out)
                st["output_summary"] = rec.summary
            except (ToolError, TypeError, ValueError, KeyError) as e:
                out = None
                rec.error = str(e)
                st["output_summary"] = {"hata": rec.error}
        rec.duration_ms = round((time.perf_counter() - t) * 1000, 1)
        return rec, out

    @staticmethod
    def _done(
        t0: float,
        calls: int,
        records: list[ToolCallRecord],
        answer: str,
        grounded: bool,
        unverified: list[str],
        note: str | None = None,
    ) -> ChatTurn:
        return ChatTurn(
            answer=answer,
            tool_calls=records,
            grounded=grounded,
            unverified=unverified,
            llm_calls=calls,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            note=note,
        )
