"""Situation-aware chat suggestions: rule-based, from the evidence packet, no LLM call (milliseconds).

The questions change with what the packet says: a contradicted identity claim, a short ETA, a convoy, a
vehicle with no track. They name evidence ids (V7, T0122, R119) but never numbers: numbers in a question
would enter the grounding bank and let an answer "prove" a value by quoting the question back.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from sentinel.domain.models import LABEL_TR, EvidencePacket, TriageRow, VehicleEvidence, Verdict
from sentinel.geo.zones import zone_display

LIMIT = 4
_REF_RE = re.compile(r"\b(?:img_\d+|[VTR]\d{1,4})\b")


class Suggestion(BaseModel):
    text: str
    reason: str  # why this question now (shown as a small label)
    refs: list[str] = []  # evidence ids the question is about (ranking follow-ups)


def _name(v: VehicleEvidence) -> str:
    return f"{v.ref} ({v.track_id})" if v.track_id else v.ref


def _vehicle_questions(v: VehicleEvidence, p: EvidencePacket) -> list[tuple[int, Suggestion]]:
    """(priority, suggestion) for one vehicle; higher priority first. One question per anomaly."""
    codes = {f.code for f in v.factors}
    refs = [v.ref] + ([v.track_id] if v.track_id else [])
    out: list[tuple[int, Suggestion]] = []
    if "identity_contradicted" in codes:
        ids = sorted(
            {
                r
                for f in v.factors
                if f.code == "identity_contradicted"
                for r in f.evidence_refs
                if r.startswith("R")
            }
        )
        rid = ids[0] if ids else "kimlik"
        out.append(
            (
                90,
                Suggestion(
                    text=f"{rid} raporundaki kimlik iddiası {_name(v)} için neden kanıtla çelişiyor?",
                    reason="çelişen kimlik iddiası",
                    refs=refs + ids,
                ),
            )
        )
    if codes & {"eta_short", "eta_mid"}:
        out.append(
            (
                80,
                Suggestion(
                    text=f"{_name(v)} üsse ne zaman ulaşır, hangi yönden geliyor?",
                    reason="kısa ETA",
                    refs=refs,
                ),
            )
        )
    elif "approaching" in codes:
        out.append(
            (
                60,
                Suggestion(
                    text=f"{_name(v)} ne zamandan beri üsse yaklaşıyor?", reason="yaklaşıyor", refs=refs
                ),
            )
        )
    if "stop_and_go" in codes and v.track_id:
        out.append(
            (
                55,
                Suggestion(
                    text=f"{v.track_id} son iki saatte nerelerde durdu?",
                    reason="dur-kalk hareketi",
                    refs=refs,
                ),
            )
        )
    if "heavy" in codes and v.track_id:
        out.append(
            (
                65,
                Suggestion(
                    text=f"{v.ref} ({LABEL_TR[v.label]}, {v.track_id}) son iki saatte hangi bölgelerden geçti?",
                    reason="ağır araç",
                    refs=refs,
                ),
            )
        )
    if "untracked" in codes:
        out.append(
            (
                50,
                Suggestion(
                    text=f"{v.ref} için hareket kaydı yok; yakınında bu araçla ilgili rapor var mı?",
                    reason="kayıtsız araç",
                    refs=refs,
                ),
            )
        )
    if v.promoted:
        out.append(
            (
                40,
                Suggestion(
                    text=f"{v.ref} düşük güvenle tespit edildi; {v.track_id} eşleşmesi güvenilir mi?",
                    reason="düşük güven",
                    refs=refs,
                ),
            )
        )
    if "leaving" in codes and v.track_id:
        out.append(
            (
                30,
                Suggestion(
                    text=f"{_name(v)} ne zamandan beri üsten uzaklaşıyor?", reason="uzaklaşıyor", refs=refs
                ),
            )
        )
    return out


def frame_suggestions(
    p: EvidencePacket, focus_ref: str | None = None, limit: int = LIMIT
) -> list[Suggestion]:
    """Questions for an open frame; with `focus_ref` (a dragged vehicle) only about that vehicle."""
    ranked: list[tuple[int, Suggestion]] = []
    vehicles = [v for v in p.vehicles if v.ref == focus_ref] if focus_ref else p.vehicles
    # riskiest first; on a tie the one that arrives soonest (its question is the more urgent one)
    for v in sorted(vehicles, key=lambda v: (-v.score, _eta(v))):
        ranked += _vehicle_questions(v, p)
    if not focus_ref:
        convoy = [v.ref for v in p.vehicles if any(f.code == "convoy" for f in v.factors)]
        if len(convoy) >= 2:
            ranked.append(
                (
                    85,
                    Suggestion(
                        text=f"{', '.join(convoy)} birlikte mi hareket ediyor, ne zamandan beri?",
                        reason="konvoy",
                        refs=convoy,
                    ),
                )
            )
        for r in p.reports:
            if r.verdict == Verdict.CELISIYOR and not r.identity_claim:
                ranked.append(
                    (
                        70,
                        Suggestion(
                            text=f"{r.report_id} raporu neden kanıtla çelişiyor?",
                            reason="çelişen rapor",
                            refs=[r.report_id],
                        ),
                    )
                )
        if p.undetected_tracks:
            t = p.undetected_tracks[0]
            ranked.append(
                (
                    45,
                    Suggestion(
                        text=f"Karede olup tespit edilemeyen {t} nereden geliyor?",
                        reason="tespit edilemeyen iz",
                        refs=[t],
                    ),
                )
            )
        if not ranked:
            ranked.append(
                (
                    10,
                    Suggestion(
                        text="Bu karede dikkat gerektiren bir durum var mı?",
                        reason="genel",
                        refs=[p.image_id],
                    ),
                )
            )
            ranked.append(
                (
                    5,
                    Suggestion(
                        text="Bu bölgede gün içinde başka neler oldu?", reason="bölge", refs=[p.image_id]
                    ),
                )
            )
    # Whole frame: one question per kind of anomaly (the riskiest vehicle's), so the list covers different things.
    return _top(ranked, limit, one_per_reason=not focus_ref)


def general_suggestions(rows: list[TriageRow], limit: int = LIMIT) -> list[Suggestion]:
    """No frame open: questions about the queue (rows in risk order)."""
    pending = [r for r in rows if not r.decision and r.level.value in ("KRİTİK", "YÜKSEK")]
    ranked: list[tuple[int, Suggestion]] = []
    if pending:
        top = pending[0]
        ranked.append(
            (
                90,
                Suggestion(text=f"{top.image_id} neden en acil kare?", reason="en acil", refs=[top.image_id]),
            )
        )
        ranked.append(
            (
                70,
                Suggestion(text="Karar bekleyen KRİTİK kareler hangileri?", reason="karar bekliyor", refs=[]),
            )
        )
    contradicted = [r for r in rows if r.reports_contradicted]
    if contradicted:
        zone = zone_display(contradicted[0].zone)
        ranked.append(
            (
                60,
                Suggestion(
                    text=f"{zone} bölgesinde hangi raporlar kanıtla çelişiyor?",
                    reason="çelişen raporlar",
                    refs=[],
                ),
            )
        )
    ranked.append(
        (
            40,
            Suggestion(text="Şu an üsse yaklaşan ağır araçlar hangi karelerde?", reason="ağır araç", refs=[]),
        )
    )
    return _top(ranked, limit)


def followups(
    base: list[Suggestion], answer: str, asked: list[str], focus_ref: str | None = None, limit: int = 3
) -> list[Suggestion]:
    """After an answer: not-yet-asked suggestions, those about ids the answer mentions (or the focus) first."""
    mentioned = set(_REF_RE.findall(answer)) | ({focus_ref} if focus_ref else set())
    fresh = [s for s in base if not any(_same_question(q, s.text) for q in asked)]
    fresh.sort(key=lambda s: not (set(s.refs) & mentioned))  # stable: keeps priority order within groups
    return fresh[:limit]


def _eta(v: VehicleEvidence) -> float:
    k = v.kinematics
    return k.eta_min if k and k.eta_min is not None else float("inf")


def _top(ranked: list[tuple[int, Suggestion]], limit: int, one_per_reason: bool = False) -> list[Suggestion]:
    seen: set[str] = set()
    out: list[Suggestion] = []
    for _, s in sorted(ranked, key=lambda x: -x[0]):  # stable: vehicles stay in score order within a priority
        key = s.reason if one_per_reason else s.text
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out[:limit]


def _same_question(asked: str, suggestion: str) -> bool:
    """The operator already asked this, maybe in other words ("bu araç" for "V7 (T0122)"). Ids must not
    disagree: "R119 neden çelişiyor?" and "R125 neden çelişiyor?" are different questions."""
    ids_a, ids_s = set(_REF_RE.findall(asked)), set(_REF_RE.findall(suggestion))
    if ids_a and not ids_a & ids_s:
        return False
    wa, ws = _words(asked), _words(suggestion)
    return bool(wa and ws) and len(wa & ws) / len(wa | ws) >= 0.6


def _words(q: str) -> set[str]:
    return {w for w in re.findall(r"\w+", _REF_RE.sub(" ", q.lower())) if len(w) > 2 and w not in _GENERIC}


_GENERIC = {"araç", "aracı", "için", "kamyon", "otomobil"}
