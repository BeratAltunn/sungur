"""Floor rules: minimum vehicle level independent of the matrix. The LLM can never go below these.

KRİTİK   urgency: approaching with ETA < floor_critical_eta_min and a confirmed heavy class or intent
         indicators YÜKSEK (a convoy of cars alone does not trigger immediate escalation)
YÜKSEK   deception close by: intent indicators and opportunity YÜKSEK, whatever the class
YÜKSEK   potential threat: capability and opportunity YÜKSEK, unless there is exculpatory evidence
         (leaving, confirmed friendly identity) — unknown intent is not absent intent
YÜKSEK   confident detection without a movement record close to the base
"""

from __future__ import annotations

from sentinel.config import RiskCfg
from sentinel.domain.models import HEAVY_LABELS, LABEL_TR, RiskLevel, ThreatProfile, VehicleEvidence
from sentinel.fmt import dec, km

_EXCULPATORY = {"leaving", "identity_confirmed"}


def floor_level(
    v: VehicleEvidence, t: ThreatProfile, reasons_i: list[str], cfg: RiskCfg
) -> tuple[RiskLevel | None, list[str]]:
    """`reasons_i`: short names of the intent indicators (for the reason text)."""
    k = v.kinematics
    codes = {f.code for f in v.factors}
    heavy = v.class_label in HEAVY_LABELS
    intent_high = t.intent.band == RiskLevel.YUKSEK
    if k and k.approaching and k.eta_min is not None and k.eta_min < cfg.floor_critical_eta_min:
        aggr = []
        if heavy:
            aggr.append(f"ağır araç ({LABEL_TR[v.class_label]})")
        if intent_high:
            aggr.append(f"niyet göstergeleri YÜKSEK ({', '.join(reasons_i)})")
        if aggr:
            return RiskLevel.KRITIK, [
                f"{v.ref}: yaklaşıyor, ETA ~{dec(k.eta_min)} dk < {cfg.floor_critical_eta_min:g} dk + "
                + " + ".join(aggr)
            ]
    high: list[str] = []
    near = t.opportunity.band == RiskLevel.YUKSEK
    if intent_high and near:
        high.append(f"{v.ref}: üsse {km(v.d_base_m)}'de niyet göstergeleri YÜKSEK ({', '.join(reasons_i)})")
    if t.capability.band == RiskLevel.YUKSEK and near and not codes & _EXCULPATORY:
        high.append(f"{v.ref}: potansiyel tehdit, yetenek ve fırsat (üsse {km(v.d_base_m)}) YÜKSEK")
    if (
        k is None
        and v.d_base_m < cfg.floor_high_untracked_km * 1000
        and v.conf >= cfg.floor_high_untracked_min_conf
    ):
        high.append(f"{v.ref}: üsse {km(v.d_base_m)}'de kayıtsız araç")
    return (RiskLevel.YUKSEK, high) if high else (None, [])
