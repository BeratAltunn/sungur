"""Floor rules: minimum level independent of the score. The LLM can never go below these."""

from __future__ import annotations

from sentinel.config import RiskCfg
from sentinel.domain.models import HEAVY_LABELS, RiskLevel, VehicleEvidence
from sentinel.fmt import dec, km


def floor_level(
    vehicles: list[VehicleEvidence], convoy: set[str], cfg: RiskCfg
) -> tuple[RiskLevel | None, list[str]]:
    critical: list[str] = []
    high: list[str] = []
    for v in vehicles:
        codes = {f.code for f in v.factors}
        k = v.kinematics
        heavy = v.label in HEAVY_LABELS
        contradicted = "identity_contradicted" in codes
        if k and k.approaching and k.eta_min is not None and k.eta_min < cfg.floor_critical_eta_min:
            aggr = [
                name
                for name, on in (
                    ("ağır araç", heavy),
                    ("konvoy", v.ref in convoy),
                    ("çelişen kimlik iddiası", contradicted),
                )
                if on
            ]
            if aggr:
                critical.append(
                    f"{v.ref}: yaklaşıyor, ETA ~{dec(k.eta_min)} dk < {cfg.floor_critical_eta_min:g} dk + {', '.join(aggr)}"
                )
        if contradicted and heavy:
            high.append(f"{v.ref}: çelişen kimlik iddiası olan noktada ağır araç")
        if (
            k is None
            and v.d_base_m < cfg.floor_high_untracked_km * 1000
            and v.conf >= cfg.floor_high_untracked_min_conf
        ):
            high.append(f"{v.ref}: üsse {km(v.d_base_m)}'de kayıtsız araç")
    if critical:
        return RiskLevel.KRITIK, critical
    if high:
        return RiskLevel.YUKSEK, high
    return None, []
