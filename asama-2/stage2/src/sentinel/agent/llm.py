"""Provider-agnostic LLM access.

- OpenAICompatLLM: GLM (or on-prem vLLM/Ollama) through the OpenAI SDK; base_url/model from .env.
- MockLLM: deterministic stand-in for tests and offline development.
- CachedLLM: file cache keyed by hash(model, prompt version, messages, tools).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from sentinel.agent.budget import BudgetGuard
from sentinel.config import LLMCfg


class LLMError(RuntimeError):
    pass


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""
    cached: bool = False


class LLMClient(Protocol):
    model: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


# ============================================================================ GLM / OpenAI-compatible
class OpenAICompatLLM:
    def __init__(self, cfg: LLMCfg, budget: BudgetGuard | None = None):
        from openai import OpenAI

        key = os.environ.get("GLM_API_KEY")
        if not key:
            raise LLMError("GLM_API_KEY tanımlı değil (.env)")
        # .env may override price/timeout, e.g. a local Ollama model: GLM_PRICE_IN=0, GLM_TIMEOUT_S=180
        env = os.environ
        self.cfg = cfg.model_copy(
            update={
                "price_in_per_mtok": float(env.get("GLM_PRICE_IN", cfg.price_in_per_mtok)),
                "price_out_per_mtok": float(env.get("GLM_PRICE_OUT", cfg.price_out_per_mtok)),
                "timeout_s": float(env.get("GLM_TIMEOUT_S", cfg.timeout_s)),
                "reasoning_effort": env.get("GLM_REASONING_EFFORT", cfg.reasoning_effort) or None,
            }
        )
        self.model = env.get("GLM_MODEL", "glm-4.5")
        self.budget = budget
        # Some gateways (e.g. Evren) authenticate with a custom header instead of "Authorization: Bearer".
        auth_header = env.get("GLM_AUTH_HEADER")
        self._client = OpenAI(
            base_url=env.get("GLM_BASE_URL"),
            api_key=key,
            timeout=self.cfg.timeout_s,
            max_retries=self.cfg.max_retries,
            default_headers={auth_header: key} if auth_header else None,
        )

    def chat(self, messages, *, json_mode=False, tools=None) -> LLMResponse:
        if self.budget:
            self.budget.check()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.cfg.reasoning_effort:
            kwargs["reasoning_effort"] = self.cfg.reasoning_effort
        if tools:
            kwargs["tools"] = tools
        try:
            r = self._client.chat.completions.create(**kwargs)
        except Exception as e:  # network, auth, rate limit, timeout: caller degrades gracefully
            raise LLMError(f"{type(e).__name__}: {e}") from e
        msg = r.choices[0].message
        t_in = getattr(r.usage, "prompt_tokens", 0) or 0
        t_out = getattr(r.usage, "completion_tokens", 0) or 0
        cost = t_in / 1e6 * self.cfg.price_in_per_mtok + t_out / 1e6 * self.cfg.price_out_per_mtok
        if self.budget:
            self.budget.add(cost)
        calls = [
            {"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
            for c in (msg.tool_calls or [])
        ]
        return LLMResponse(
            content=msg.content,
            tool_calls=calls,
            tokens_in=t_in,
            tokens_out=t_out,
            cost_usd=cost,
            model=self.model,
        )


# ============================================================================ Mock
Responder = Callable[[list[dict[str, Any]], bool, list[dict[str, Any]] | None], str]


class MockLLM:
    """Deterministic LLM for tests/offline. Default responder writes a brief from the masked packet
    embedded in the user message (so it only uses packet numbers)."""

    model = "mock"

    def __init__(self, responder: Responder | None = None):
        self.responder = responder or default_mock_responder
        self.calls: list[list[dict[str, Any]]] = []

    def chat(self, messages, *, json_mode=False, tools=None) -> LLMResponse:
        self.calls.append(messages)
        content = self.responder(messages, json_mode, tools)
        n_in = sum(len(str(m.get("content", ""))) for m in messages) // 4
        return LLMResponse(content=content, tokens_in=n_in, tokens_out=len(content) // 4, model=self.model)


def extract_packet(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for msg in reversed(messages):
        if msg["role"] != "user":
            continue
        m = re.search(r"<kanit_paketi>\s*(\{.*?\})\s*</kanit_paketi>", str(msg["content"]), re.S)
        if m:
            return json.loads(m.group(1))
    raise LLMError("mock: kanıt paketi bulunamadı")


def default_mock_responder(messages, json_mode, tools) -> str:
    p = extract_packet(messages)
    k, risk, cnt = p["kare"], p["risk"], p["sayimlar"]
    top = next((v for v in p["araclar"] if v["ref"] == risk.get("en_riskli_arac")), None)
    if top and top.get("yaklasiyor"):
        head = (
            f"{k['bolge']} bölgesinde {cnt['yaklasan_arac']} araç üsse yaklaşıyor; "
            f"{top['ref']} üsse {str(top['uste_km']).replace('.', ',')} km'de"
            + (f", ETA ~{str(top['eta_dk']).replace('.', ',')} dk." if top.get("eta_dk") is not None else ".")
        )
    else:
        head = f"{k['bolge']} bölgesinde {cnt['arac']} araç; belirgin yaklaşma yok."
    findings = [
        {
            "vehicle_ref": v["ref"],
            "statement": f"{v['ref']} üsse {str(v['uste_km']).replace('.', ',')} km, skor {v['skor']}.",
            "evidence_refs": [x for x in (v["ref"], v.get("track")) if x],
        }
        for v in sorted(p["araclar"], key=lambda v: -v["skor"])[:3]
    ]
    return json.dumps(
        {
            "image_id": k["id"],
            "risk_level": risk["kural_seviyesi"],
            "risk_score": risk["skor"],
            "headline": head,
            "key_findings": findings,
            "report_assessment": [
                {"report_id": r["id"], "verdict": r["karar"], "reason": r["gerekce"]} for r in p["raporlar"]
            ],
            "recommended_action": "Kural seviyesine göre eylem uygulanmalı.",
            "confidence": "orta",
            "uncertainties": p["belirsizlikler"],
        },
        ensure_ascii=False,
    )


# ============================================================================ Cache
class CachedLLM:
    def __init__(self, inner: LLMClient, cache_dir: Path, namespace: str = ""):
        self.inner = inner
        self.model = inner.model
        self.dir = Path(cache_dir)
        self.namespace = namespace

    def key(self, messages, json_mode, tools) -> str:
        blob = json.dumps(
            {"m": self.model, "ns": self.namespace, "msgs": messages, "json": json_mode, "tools": tools},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def peek(self, messages, *, json_mode=False, tools=None) -> LLMResponse | None:
        """Cached answer without any network call (None on miss)."""
        p = self.dir / f"{self.key(messages, json_mode, tools)}.json"
        if not p.exists():
            return None
        r = LLMResponse.model_validate_json(p.read_text(encoding="utf-8"))
        return r.model_copy(update={"cached": True, "cost_usd": 0.0}) if _usable(r) else None

    def chat(self, messages, *, json_mode=False, tools=None) -> LLMResponse:
        p = self.dir / f"{self.key(messages, json_mode, tools)}.json"
        if p.exists():
            r = LLMResponse.model_validate_json(p.read_text(encoding="utf-8"))
            if _usable(r):  # entries written before empty responses were filtered are ignored
                return r.model_copy(update={"cached": True, "cost_usd": 0.0})
        r = self.inner.chat(messages, json_mode=json_mode, tools=tools)
        if _usable(r):  # never cache an empty answer (e.g. token budget spent on reasoning)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(r.model_dump_json(), encoding="utf-8")
        return r


def _usable(r: LLMResponse) -> bool:
    return bool((r.content or "").strip() or r.tool_calls)


def build_llm(cfg: LLMCfg, cache_dir: Path, budget: BudgetGuard) -> LLMClient:
    inner: LLMClient = MockLLM() if cfg.provider == "mock" else OpenAICompatLLM(cfg, budget)
    if not cfg.cache:
        return inner
    # generation settings are part of the key: changing them must not reuse old answers
    ns = f"{cfg.prompt_version}|{cfg.max_tokens}|{cfg.reasoning_effort}|{cfg.temperature}"
    return CachedLLM(inner, cache_dir, ns)
