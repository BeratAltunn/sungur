"""Analyst: exactly one LLM call per frame (+ at most one correction), grounded, with template fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sentinel.agent import grounding
from sentinel.agent.budget import BudgetExceeded
from sentinel.agent.llm import LLMClient, LLMError, LLMResponse
from sentinel.agent.masking import mask_packet, render_user_message
from sentinel.agent.template import template_brief
from sentinel.config import Settings
from sentinel.domain.models import EvidencePacket, GroundingResult, RiskBrief
from sentinel.observability.trace import Tracer

PROMPTS_DIR = Path(__file__).parent / "prompts"
CACHE_MISS_NOTE = "LLM yanıtı henüz hazır değil (önizleme); kural tabanlı brief"


@dataclass
class BriefOutcome:
    brief: RiskBrief
    source: str  # "llm" | "llm_cache" | "template"
    grounding: GroundingResult
    note: str | None = None


def load_prompt(version: str) -> str:
    return (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")


class Analyst:
    def __init__(self, llm: LLMClient | None, settings: Settings):
        self.llm = llm
        self.s = settings
        self.cfg = settings.llm
        self.system = load_prompt(self.cfg.prompt_version)

    def constants(self) -> dict[str, Any]:
        t, r = self.s.tracking, self.s.risk
        return {
            "iz_penceresi_saat": t.window_min // 60,
            "iz_penceresi_dk": t.window_min,
            "yaklasma_olcum_penceresi_dk": t.closing_window_min,
            "rapor_yaricapi_m": self.s.reports.radius_m,
            "kritik_taban_eta_esigi_dk": r.floor_critical_eta_min,
            "yakinlik_esikleri_km": [r.near_km, r.mid_km],
        }

    # ------------------------------------------------------------------ main
    def brief(
        self, packet: EvidencePacket, tracer: Tracer, use_llm: bool = True, cache_only: bool = False
    ) -> BriefOutcome:
        """cache_only: use a cached LLM answer if there is one, never call the network (fast previews)."""
        masked = mask_packet(packet, self.constants())
        if not use_llm or self.llm is None:
            return self._template(packet, masked, tracer, "LLM kapalı: kural tabanlı brief")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": render_user_message(packet, masked)},
        ]
        if cache_only:
            peek = getattr(self.llm, "peek", None)
            with tracer.step(
                "6_llm_önbellek", {"model": self.llm.model, "prompt": self.cfg.prompt_version}
            ) as st:
                resp = peek(messages, json_mode=True) if peek else None
                st["cache_hit"] = resp is not None
                brief, _ = self._parse(resp.content, packet) if resp else (None, "")
                if brief is not None:
                    g = grounding.check(brief, packet, masked, self.cfg.max_level_deviation)
                    st["grounding"] = {
                        "checked": g.checked,
                        "failed": g.failed,
                        "unknown_refs": g.unknown_refs,
                    }
                    if g.passed:
                        st["output_summary"] = {"seviye": brief.risk_level.value, "manşet": brief.headline}
                        return BriefOutcome(brief, "llm_cache", g)
                st["output_summary"] = {"sorun": "önbellekte geçerli yanıt yok"}
            return self._template(packet, masked, tracer, CACHE_MISS_NOTE)
        last_issue = ""
        for attempt in (1, 2):
            with tracer.step(
                f"6_llm_analist_{attempt}", {"model": self.llm.model, "prompt": self.cfg.prompt_version}
            ) as st:
                try:
                    resp = self.llm.chat(messages, json_mode=True)
                except (LLMError, BudgetExceeded) as e:
                    st["error"] = str(e)
                    return self._template(
                        packet, masked, tracer, f"LLM erişilemedi ({e}); kural tabanlı brief"
                    )
                st["cache_hit"] = resp.cached
                st["llm"] = _usage(resp, self.cfg.prompt_version)
                brief, issue = self._parse(resp.content, packet)
                if brief is not None:
                    g = grounding.check(brief, packet, masked, self.cfg.max_level_deviation)
                    st["grounding"] = {
                        "checked": g.checked,
                        "failed": g.failed,
                        "unknown_refs": g.unknown_refs,
                        "level": g.level_issue,
                    }
                    if g.passed:
                        st["output_summary"] = {"seviye": brief.risk_level.value, "manşet": brief.headline}
                        return BriefOutcome(brief, "llm_cache" if resp.cached else "llm", g)
                    issue = _grounding_feedback(g)
                st["output_summary"] = {"sorun": issue}
                last_issue = issue
            messages = messages + [
                {"role": "assistant", "content": resp.content or ""},
                {
                    "role": "user",
                    "content": f"Brief reddedildi: {issue}\nKurallara uyarak JSON'u yeniden üret.",
                },
            ]
        return self._template(
            packet, masked, tracer, f"LLM brief'i doğrulamadan geçemedi ({last_issue}); kural tabanlı brief"
        )

    # ------------------------------------------------------------------ helpers
    def _parse(self, content: str | None, packet: EvidencePacket) -> tuple[RiskBrief | None, str]:
        if not content:
            return None, "boş yanıt"
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            data = json.loads(text)
            data["image_id"] = packet.image_id
            return RiskBrief.model_validate(data), ""
        except (json.JSONDecodeError, ValidationError) as e:
            return None, f"şema hatası: {str(e)[:300]}"

    def _template(self, packet: EvidencePacket, masked: dict, tracer: Tracer, note: str) -> BriefOutcome:
        with tracer.step("6_şablon_brief", {"neden": note}) as st:
            b = template_brief(packet)
            g = grounding.check(b, packet, masked, self.cfg.max_level_deviation)
            st["output_summary"] = {"seviye": b.risk_level.value, "manşet": b.headline}
            st["grounding"] = {"checked": g.checked, "failed": g.failed, "unknown_refs": g.unknown_refs}
        return BriefOutcome(b, "template", g, note)


def _usage(r: LLMResponse, prompt_version: str) -> dict[str, Any]:
    return {
        "model": r.model,
        "prompt_version": prompt_version,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "cost_usd": round(r.cost_usd, 6),
        "cached": r.cached,
    }


def _grounding_feedback(g: GroundingResult) -> str:
    parts = []
    if g.failed:
        parts.append("pakette olmayan sayı/saat veya değiştirilmiş karar: " + "; ".join(g.failed[:8]))
    if g.unknown_refs:
        parts.append("bilinmeyen kimlikler: " + ", ".join(g.unknown_refs[:8]))
    if g.level_issue:
        parts.append(g.level_issue)
    return " | ".join(parts)
