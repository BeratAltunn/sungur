"""Situation-aware chat suggestions: rule-based, from the evidence packet, no LLM call (milliseconds).

The questions change with what the packet says: a contradicted identity claim, a short ETA, a convoy, a
vehicle with no track. They name evidence ids (V7, T0122, R119) but never numbers: numbers in a question
would enter the grounding bank and let an answer "prove" a value by quoting the question back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    # ETA is not a risk factor in the C-O-I model (it drives the floors and queue order): read it from the
    # kinematics. The soonest arrival in the frame asks first.
    k = v.kinematics
    etas = [w.kinematics.eta_min for w in p.vehicles if w.kinematics and w.kinematics.approaching]
    etas = [e for e in etas if e is not None]
    if k and k.approaching and k.eta_min is not None:
        out.append(
            (
                80 if k.eta_min <= min(etas) else 70,
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
    if (
        k and k.stop_and_go and v.track_id
    ):  # context only in the C-O-I model, not a factor: read the kinematics
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


@dataclass(frozen=True)
class CtxVehicle:
    """A vehicle the operator put in the chat's context (resolved against its frame's packet)."""

    packet: EvidencePacket
    v: VehicleEvidence

    @property
    def name(self) -> str:  # tracks are global ids; a bare V-ref needs its frame
        return self.v.track_id or f"{self.v.ref} ({self.packet.image_id})"


@dataclass(frozen=True)
class CtxFrame:
    packet: EvidencePacket


def context_suggestions(items: list[CtxVehicle | CtxFrame], limit: int = LIMIT) -> list[Suggestion]:
    """Questions for what the operator put together in the chat: one item → the usual questions about it,
    several → questions that connect them (moving together, which is more urgent, did one pass the other's area)."""
    if not items:
        return []
    if len(items) == 1:
        it = items[0]
        if isinstance(it, CtxVehicle):
            return frame_suggestions(it.packet, it.v.ref, limit)
        return frame_suggestions(it.packet, None, limit)
    vehicles = [i for i in items if isinstance(i, CtxVehicle)]
    frames = [i for i in items if isinstance(i, CtxFrame)]
    ranked: list[tuple[int, Suggestion]] = []

    if len(vehicles) >= 2:
        a, b = vehicles[0], vehicles[1]
        names = [x.name for x in vehicles]
        refs = [r for x in vehicles for r in (x.v.ref, x.v.track_id) if r]
        joined = ", ".join(names[:-1]) + f" ve {names[-1]}"
        if all(x.v.track_id for x in vehicles):
            ranked.append(
                (
                    90,
                    Suggestion(
                        text=f"{joined} birlikte mi hareket ediyor, ne zamandan beri?",
                        reason="birlikte hareket",
                        refs=refs,
                    ),
                )
            )
            ranked.append(
                (
                    70,
                    Suggestion(
                        text=f"{joined} son iki saatte aynı bölgelerden geçti mi?",
                        reason="ortak güzergâh",
                        refs=refs,
                    ),
                )
            )
        if any(x.v.kinematics and x.v.kinematics.approaching for x in vehicles):
            ranked.append(
                (
                    85,
                    Suggestion(
                        text=f"{joined} arasında hangisi üsse önce ulaşır?", reason="karşılaştırma", refs=refs
                    ),
                )
            )
        for x in (a, b):  # plus each one's most urgent own question
            own = _vehicle_questions(x.v, x.packet)
            if own:
                pr, q = max(own, key=lambda t: t[0])
                ranked.append((pr - 30, q))

    if len(frames) >= 2:
        fa, fb = frames[0].packet, frames[1].packet
        ids = [f.packet.image_id for f in frames]
        joined = ", ".join(ids[:-1]) + f" ve {ids[-1]}"
        ranked.append(
            (
                88,
                Suggestion(
                    text=f"{joined} karelerinden hangisi daha acil, neden?", reason="karşılaştırma", refs=ids
                ),
            )
        )
        if fa.frame.zone == fb.frame.zone:
            zone = zone_display(fa.frame.zone)
            ranked.append(
                (
                    80,
                    Suggestion(
                        text=f"{zone} bölgesinde {fa.image_id} ile {fb.image_id} arasında ne değişti?",
                        reason="aynı bölge",
                        refs=ids,
                    ),
                )
            )
        else:
            ranked.append(
                (
                    60,
                    Suggestion(
                        text=f"{joined} karelerindeki araçlar aynı yöne mi gidiyor?", reason="yön", refs=ids
                    ),
                )
            )
        if all(any(r.verdict == Verdict.CELISIYOR for r in f.packet.reports) for f in frames[:2]):
            ranked.append(
                (
                    75,
                    Suggestion(
                        text=f"{joined} karelerinde kanıtla çelişen raporlar birbiriyle ilgili mi?",
                        reason="çelişen raporlar",
                        refs=ids,
                    ),
                )
            )

    # A vehicle that drove through another item's area (from its own track, not a guess).
    for x in vehicles:
        passed = set(x.v.kinematics.zones_passed) if x.v.kinematics else set()
        for f in frames:
            if f.packet.image_id != x.packet.image_id and f.packet.frame.zone in passed:
                zone = zone_display(f.packet.frame.zone)
                ranked.append(
                    (
                        92,
                        Suggestion(
                            text=f"{x.name}, {f.packet.image_id} karesinin bölgesinden ({zone}) geçmiş; oradayken ne yapıyordu?",
                            reason="bölgeden geçti",
                            refs=[r for r in (x.v.ref, x.v.track_id, f.packet.image_id) if r],
                        ),
                    )
                )
    for f in frames:  # frame + vehicles of other frames: is it the same situation?
        for x in vehicles:
            if x.packet.image_id != f.packet.image_id:
                ranked.append(
                    (
                        55,
                        Suggestion(
                            text=f"{x.name} ile {f.packet.image_id} karesindeki araçlar arasında bağlantı var mı?",
                            reason="bağlantı",
                            refs=[x.v.ref, f.packet.image_id],
                        ),
                    )
                )
    # Fill with each item's own most urgent questions (below the connecting ones).
    for it in items:
        ranked += [(40 - i, s) for i, s in enumerate(context_suggestions([it], 2))]
    return _top(ranked, limit, one_per_reason=True)


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
