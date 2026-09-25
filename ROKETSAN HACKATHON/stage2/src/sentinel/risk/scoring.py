"""Explainable rule score: frame score = max vehicle score + load bonus + frame factors, then floors."""

from __future__ import annotations

from sentinel.config import RiskCfg
from sentinel.domain.models import ReportVerification, RiskAssessment, RiskFactor, RiskLevel, VehicleEvidence
from sentinel.risk.features import convoy_members, frame_factors, vehicle_factors
from sentinel.risk.floors import floor_level


def level_for(score: int, cfg: RiskCfg) -> RiskLevel:
    lv = cfg.levels
    if score >= lv["KRITIK"]:
        return RiskLevel.KRITIK
    if score >= lv["YUKSEK"]:
        return RiskLevel.YUKSEK
    if score >= lv["ORTA"]:
        return RiskLevel.ORTA
    return RiskLevel.DUSUK


def assess(
    vehicles: list[VehicleEvidence], reports: list[ReportVerification], cfg: RiskCfg
) -> RiskAssessment:
    """Mutates `vehicles` in place (score, factors) and returns the frame assessment."""
    convoy = convoy_members(vehicles, cfg)
    for v in vehicles:
        v.factors = vehicle_factors(v, reports, convoy, cfg)
        v.score = max(0, min(100, sum(f.points for f in v.factors)))

    top = max(vehicles, key=lambda v: v.score, default=None)
    frame_f: list[RiskFactor] = frame_factors(reports, vehicles, cfg)
    n_appr = sum(1 for v in vehicles if v.kinematics and v.kinematics.approaching)
    extra = max(0, n_appr - 1)
    if extra:
        bonus = min(cfg.load_bonus_cap, extra * cfg.load_bonus_per_vehicle)
        frame_f.append(RiskFactor(code="load", label=f"Toplam yük: {extra} ek yaklaşan araç", points=bonus))

    raw = (top.score if top else 0) + sum(f.points for f in frame_f)
    score = int(max(0, min(100, raw)))
    score_level = level_for(score, cfg)
    floor, reasons = floor_level(vehicles, convoy, cfg)
    level = max(score_level, floor, key=lambda lv: lv.rank) if floor else score_level
    return RiskAssessment(
        score=score,
        score_level=score_level,
        floor_level=floor,
        floor_reasons=reasons,
        level=level,
        factors=frame_f,
        top_vehicle=top.ref if top else None,
    )
