"""Critical cards for the chat: every KRİTİK frame still waiting for the operator, with the few facts that
make it critical and the questions worth asking. Rule-based from the evidence packet: no LLM call, no cost,
so the cards can be shown the moment a frame turns KRİTİK."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from sentinel.agent.suggest import Suggestion, frame_suggestions
from sentinel.domain.models import HEAVY_LABELS, LABEL_TR, EvidencePacket, RiskLevel, TriageRow, Verdict
from sentinel.geo.zones import zone_display

MAX_FACTS = 3


class CriticalCard(BaseModel):
    image_id: str
    zone: str
    capture_time: str
    score: int
    eta_min: float | None = None  # soonest arrival among approaching vehicles
    eta_vehicle: str | None = None  # "V7 · kamyon · T0122"
    facts: list[str]
    questions: list[Suggestion]


def critical_cards(rows: list[TriageRow], packet_of: Callable[[str], EvidencePacket]) -> list[CriticalCard]:
    """KRİTİK frames without a decision, in queue (risk) order."""
    return [
        _card(r, packet_of(r.image_id)) for r in rows if r.level == RiskLevel.KRITIK and r.decision is None
    ]


def _card(r: TriageRow, p: EvidencePacket) -> CriticalCard:
    approaching = [v for v in p.vehicles if v.kinematics and v.kinematics.approaching]
    timed = [v for v in approaching if v.kinematics.eta_min is not None]
    first = min(timed, key=lambda v: v.kinematics.eta_min) if timed else None

    facts: list[str] = []
    contradicted = [x.report_id for x in p.reports if x.verdict == Verdict.CELISIYOR]
    if contradicted:
        more = f" (+{len(contradicted) - 3})" if len(contradicted) > 3 else ""
        facts.append(f"{', '.join(contradicted[:3])}{more} kanıtla çelişiyor")
    convoy = [v.ref for v in p.vehicles if any(f.code == "convoy" for f in v.factors)]
    if convoy:
        facts.append(f"{len(convoy)} araç konvoy halinde yaklaşıyor ({', '.join(convoy)})")
    elif approaching:
        facts.append(f"{len(approaching)} araç üsse yaklaşıyor")
    heavy = [v for v in approaching if v.label in HEAVY_LABELS]
    if heavy:
        facts.append(f"{len(heavy)} ağır araç yaklaşıyor ({', '.join(v.ref for v in heavy)})")
    if p.untracked:
        facts.append(f"{len(p.untracked)} araç kayıtsız ({', '.join(p.untracked)})")

    return CriticalCard(
        image_id=r.image_id,
        zone=zone_display(r.zone),
        capture_time=r.capture_time,
        score=r.score,
        eta_min=first.kinematics.eta_min if first else None,
        eta_vehicle=(
            " · ".join(x for x in (first.ref, LABEL_TR[first.label], first.track_id) if x) if first else None
        ),
        facts=facts[:MAX_FACTS],
        questions=frame_suggestions(p, None, 3),
    )
