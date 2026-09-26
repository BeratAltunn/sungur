"""Capability–Opportunity–Intent threat assessment.

Per vehicle: three 0–100 sub-scores → DÜŞÜK/ORTA/YÜKSEK bands → level from the matrix below, raised by the
floors. The score (geometric mean of the sub-scores) only orders vehicles and frames within a level.
Frame level = highest vehicle level.

    all three YÜKSEK                     → KRİTİK
    two YÜKSEK + one ORTA                → YÜKSEK
    none DÜŞÜK (otherwise)               → ORTA
    one DÜŞÜK + at least one YÜKSEK      → ORTA   (a missing element: the threat cannot materialise)
    one DÜŞÜK otherwise, two+ DÜŞÜK      → DÜŞÜK
"""

from __future__ import annotations

from sentinel.config import RiskCfg
from sentinel.domain.models import (
    ReportVerification,
    RiskAssessment,
    RiskLevel,
    ThreatDimension,
    ThreatProfile,
    VehicleEvidence,
)
from sentinel.risk.features import convoy_members, dimension_score, loose_identity_reports, vehicle_factors
from sentinel.risk.floors import floor_level

_INTENT_NAMES = {
    "approaching": "yaklaşıyor",
    "identity_contradicted": "çelişen kimlik iddiası",
    "identity_contradicted_frame": "kare çevresinde çelişen kimlik iddiası",
    "untracked": "kayıtsız araç",
}


def band(score: int, bands: dict[str, int]) -> RiskLevel:
    if score >= bands["YUKSEK"]:
        return RiskLevel.YUKSEK
    if score >= bands["ORTA"]:
        return RiskLevel.ORTA
    return RiskLevel.DUSUK


def opportunity_band(d_base_m: float, cfg: RiskCfg) -> RiskLevel:
    d_km = d_base_m / 1000
    if d_km < cfg.near_km:
        return RiskLevel.YUKSEK
    if d_km < cfg.mid_km:
        return RiskLevel.ORTA
    return RiskLevel.DUSUK


def matrix_level(capability: RiskLevel, opportunity: RiskLevel, intent: RiskLevel) -> RiskLevel:
    bands = (capability, opportunity, intent)
    lows = sum(b == RiskLevel.DUSUK for b in bands)
    highs = sum(b == RiskLevel.YUKSEK for b in bands)
    if lows >= 2:
        return RiskLevel.DUSUK
    if lows == 1:
        return RiskLevel.ORTA if highs else RiskLevel.DUSUK
    if highs == 3:
        return RiskLevel.KRITIK
    if highs == 2:
        return RiskLevel.YUKSEK
    return RiskLevel.ORTA


def ordering_score(c: int, o: int, i: int) -> int:
    return round((max(0, c) * max(0, o) * max(0, i)) ** (1 / 3))


def assess(
    vehicles: list[VehicleEvidence], reports: list[ReportVerification], cfg: RiskCfg
) -> RiskAssessment:
    """Mutates `vehicles` in place (factors, threat profile, level, score) and returns the frame assessment."""
    convoy = convoy_members(vehicles, cfg)
    loose = loose_identity_reports(reports, vehicles)
    for v in vehicles:
        v.factors = vehicle_factors(v, vehicles, reports, convoy, loose, cfg)
        c, o, i = (dimension_score(v.factors, d) for d in ("yetenek", "firsat", "niyet"))
        cb = band(c, cfg.capability_bands)
        ob = opportunity_band(v.d_base_m, cfg)
        ib = band(i, cfg.intent_bands)
        t = ThreatProfile(
            capability=ThreatDimension(score=c, band=cb),
            opportunity=ThreatDimension(score=o, band=ob),
            intent=ThreatDimension(score=i, band=ib),
            matrix_level=matrix_level(cb, ob, ib),
        )
        codes = {f.code for f in v.factors}
        reasons_i = [name for code, name in _INTENT_NAMES.items() if code in codes]
        t.floor_level, t.floor_reasons = floor_level(v, t, reasons_i, cfg)
        v.threat = t
        v.level = max(t.matrix_level, t.floor_level or RiskLevel.DUSUK, key=lambda lv: lv.rank)
        v.score = ordering_score(c, o, i)

    top = max(vehicles, key=lambda v: (v.level.rank, v.score), default=None)
    floors = [v.threat.floor_level for v in vehicles if v.threat and v.threat.floor_level]
    return RiskAssessment(
        score=top.score if top else 0,
        score_level=max(
            (v.threat.matrix_level for v in vehicles if v.threat),
            key=lambda lv: lv.rank,
            default=RiskLevel.DUSUK,
        ),
        floor_level=max(floors, key=lambda lv: lv.rank) if floors else None,
        floor_reasons=[r for v in vehicles if v.threat for r in v.threat.floor_reasons],
        level=top.level if top else RiskLevel.DUSUK,
        factors=[],
        top_vehicle=top.ref if top else None,
    )
