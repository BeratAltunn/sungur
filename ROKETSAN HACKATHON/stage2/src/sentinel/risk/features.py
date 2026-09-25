"""Per-vehicle risk factors. Every contribution is returned with a Turkish label so the UI can
show *why* (no hidden score)."""

from __future__ import annotations

from sentinel.config import RiskCfg
from sentinel.domain.models import (
    HEAVY_LABELS,
    LABEL_TR,
    ReportVerification,
    RiskFactor,
    VehicleEvidence,
    Verdict,
)
from sentinel.fmt import dec, km
from sentinel.geo.geodesy import angle_diff


def convoy_members(vehicles: list[VehicleEvidence], cfg: RiskCfg) -> set[str]:
    """Refs of vehicles approaching together (≥ convoy_min_size, similar heading)."""
    appr = [
        v
        for v in vehicles
        if v.kinematics and v.kinematics.approaching and v.kinematics.heading_deg is not None
    ]
    members: set[str] = set()
    for v in appr:
        group = [
            w
            for w in appr
            if angle_diff(w.kinematics.heading_deg, v.kinematics.heading_deg) <= cfg.convoy_heading_tol_deg
        ]
        if len(group) >= cfg.convoy_min_size:
            members.update(w.ref for w in group)
    return members


def identity_reports_for(v: VehicleEvidence, reports: list[ReportVerification]) -> tuple[list, list]:
    """(contradicted, confirmed) identity reports tied to this vehicle's track."""
    if not v.track_id:
        return [], []
    mine = [r for r in reports if r.identity_claim and v.track_id in r.related_tracks]
    return (
        [r for r in mine if r.verdict == Verdict.CELISIYOR],
        [r for r in mine if r.verdict == Verdict.DOGRULANDI],
    )


def vehicle_factors(
    v: VehicleEvidence,
    reports: list[ReportVerification],
    convoy: set[str],
    cfg: RiskCfg,
) -> list[RiskFactor]:
    w = cfg.weights
    f: list[RiskFactor] = []
    ref = v.ref
    ev = [ref] + ([v.track_id] if v.track_id else [])

    def add(code: str, label: str, pts: int, refs: list[str] | None = None) -> None:
        f.append(RiskFactor(code=code, label=label, points=pts, vehicle_ref=ref, evidence_refs=refs or ev))

    d_km = v.d_base_m / 1000
    if d_km < cfg.near_km:
        add("proximity_near", f"Üsse {km(v.d_base_m)} (< {cfg.near_km:g} km)", w.proximity_near)
    elif d_km < cfg.mid_km:
        add("proximity_mid", f"Üsse {km(v.d_base_m)} ({cfg.near_km:g}–{cfg.mid_km:g} km)", w.proximity_mid)

    if v.label in HEAVY_LABELS:
        add("heavy", f"Ağır araç ({LABEL_TR[v.label]})", w.heavy)

    k = v.kinematics
    if k is None:
        add("untracked", "Hareket kaydı yok (kayıtsız araç)", w.untracked)
    else:
        if k.approaching:
            add("approaching", f"Üsse hızla yaklaşıyor ({dec(k.closing_mps)} m/s)", w.approaching)
            if k.eta_min is not None and k.eta_min < cfg.eta_short_min:
                add("eta_short", f"ETA ~{dec(k.eta_min)} dk (< {cfg.eta_short_min:g} dk)", w.eta_short)
            elif k.eta_min is not None and k.eta_min < cfg.eta_mid_min:
                add("eta_mid", f"ETA ~{dec(k.eta_min)} dk (< {cfg.eta_mid_min:g} dk)", w.eta_mid)
        if k.stop_and_go:
            add(
                "stop_and_go",
                f"Dur-kalk yaklaşma ({len(k.stops)} duraklama, {k.stop_total_min} dk)",
                w.stop_and_go,
            )
        if k.leaving:
            add("leaving", f"Üsten uzaklaşıyor ({dec(abs(k.closing_mps))} m/s)", w.leaving)
    if ref in convoy:
        add("convoy", "Konvoy: benzer yönde birlikte yaklaşan araçlar", w.convoy)

    contradicted, confirmed = identity_reports_for(v, reports)
    if contradicted:
        ids = [r.report_id for r in contradicted]
        add(
            "identity_contradicted",
            f"Kanıtla çelişen kimlik/dost iddiası ({', '.join(ids)})",
            w.identity_contradicted,
            ev + ids,
        )
    elif confirmed:
        ids = [r.report_id for r in confirmed]
        add(
            "identity_confirmed",
            f"Kanıtla tutarlı dost kimliği ({', '.join(ids)})",
            w.identity_confirmed,
            ev + ids,
        )
    return f


def frame_factors(
    reports: list[ReportVerification], vehicles: list[VehicleEvidence], cfg: RiskCfg
) -> list[RiskFactor]:
    """Frame-level: contradicted identity claim right at the frame not tied to any matched track."""
    tied = {r.report_id for v in vehicles for r in identity_reports_for(v, reports)[0]}
    loose = [
        r
        for r in reports
        if r.identity_claim
        and r.verdict == Verdict.CELISIYOR
        and r.report_id not in tied
        and r.relevance.startswith("kare çevresinde")
    ]
    if not loose:
        return []
    ids = [r.report_id for r in loose]
    return [
        RiskFactor(
            code="identity_contradicted_frame",
            label=f"Kare çevresinde kanıtla çelişen kimlik iddiası ({', '.join(ids)})",
            points=cfg.weights.identity_contradicted,
            evidence_refs=ids,
        )
    ]
