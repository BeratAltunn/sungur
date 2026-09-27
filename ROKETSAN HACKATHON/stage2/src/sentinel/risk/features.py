"""Per-vehicle Capability–Opportunity–Intent factors. Every contribution is returned with a Turkish label
and the dimension it feeds, so the UI can show *why* (no hidden score).

    Yetenek (ne)            class of the vehicle, or its group when it is part of a convoy
    Fırsat (nerede)         distance to the base
    Niyet göstergeleri      what it does: approaching, deception, no movement record, leaving, confirmed friend

Approach is scored only as intent; ETA is not a dimension (urgency: floors + queue order, see floors.py).
Stop-and-go is context only: in this data almost every vehicle waits and moves, so it does not discriminate.
"""

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


def convoy_members(vehicles: list[VehicleEvidence], cfg: RiskCfg) -> dict[str, list[str]]:
    """{ref: refs of its group} for vehicles approaching together (≥ convoy_min_size, similar heading)."""
    appr = [
        v
        for v in vehicles
        if v.kinematics and v.kinematics.approaching and v.kinematics.heading_deg is not None
    ]
    groups: dict[str, list[str]] = {}
    for v in appr:
        group = [
            w
            for w in appr
            if angle_diff(w.kinematics.heading_deg, v.kinematics.heading_deg) <= cfg.convoy_heading_tol_deg
        ]
        if len(group) >= cfg.convoy_min_size:
            refs = [w.ref for w in group]
            for r in refs:
                groups[r] = sorted(set(groups.get(r, [])) | set(refs), key=lambda x: int(x[1:]))
    return groups


def identity_reports_for(v: VehicleEvidence, reports: list[ReportVerification]) -> tuple[list, list]:
    """(contradicted, confirmed) identity reports tied to this vehicle's track."""
    if not v.track_id:
        return [], []
    mine = [r for r in reports if r.identity_claim and v.track_id in r.related_tracks]
    return (
        [r for r in mine if r.verdict == Verdict.CELISIYOR],
        [r for r in mine if r.verdict == Verdict.DOGRULANDI],
    )


def loose_identity_reports(reports: list[ReportVerification], vehicles: list[VehicleEvidence]) -> list[str]:
    """Contradicted identity claims right at the frame that could not be tied to any of its vehicles."""
    tied = {r.report_id for v in vehicles for r in identity_reports_for(v, reports)[0]}
    return [
        r.report_id
        for r in reports
        if r.identity_claim
        and r.verdict == Verdict.CELISIYOR
        and r.report_id not in tied
        and r.relevance.startswith("kare çevresinde")
    ]


def vehicle_factors(
    v: VehicleEvidence,
    vehicles: list[VehicleEvidence],
    reports: list[ReportVerification],
    convoy: dict[str, list[str]],
    loose: list[str],
    cfg: RiskCfg,
) -> list[RiskFactor]:
    c, w = cfg.capability, cfg.weights
    f: list[RiskFactor] = []
    ref = v.ref
    ev = [ref] + ([v.track_id] if v.track_id else [])

    def add(dim: str, code: str, label: str, pts: int, refs: list[str] | None = None) -> None:
        f.append(
            RiskFactor(
                code=code, label=label, points=pts, vehicle_ref=ref, evidence_refs=refs or ev, dimension=dim
            )
        )

    # ---------------------------------------------------------------- Yetenek: ne
    base = getattr(c, v.class_label)
    if v.class_label == "unknown":
        why = "tespit güveni düşük" if v.label != "unknown" else "detektör sınıf vermiyor"
        add("yetenek", "class_unknown", f"Sınıf bilinmiyor ({why}); ağır araç dışlanamaz", base)
    else:
        code = "heavy" if v.class_label in HEAVY_LABELS else "class"
        add("yetenek", code, f"Sınıf: {LABEL_TR[v.class_label]}", base)
    if ref in convoy:
        group = [x for x in vehicles if x.ref in convoy[ref]]
        n_heavy = sum(x.class_label in HEAVY_LABELS for x in group)
        grp = min(100, c.convoy + c.convoy_heavy_bonus * n_heavy)
        heavy_note = f", {n_heavy} ağır araç" if n_heavy else ""
        add(
            "yetenek",
            "convoy",
            f"Konvoy: {len(group)} araç birlikte yaklaşıyor{heavy_note} (grup yeteneği)",
            max(0, grp - base),
            [x.ref for x in group],
        )

    # ---------------------------------------------------------------- Fırsat: nerede
    d_km = v.d_base_m / 1000
    opp = round(100 * max(0.0, min(1.0, 1 - d_km / cfg.opportunity_zero_km)))
    if d_km < cfg.near_km:
        add("firsat", "proximity_near", f"Üsse {km(v.d_base_m)} (< {cfg.near_km:g} km)", opp)
    elif d_km < cfg.mid_km:
        add("firsat", "proximity_mid", f"Üsse {km(v.d_base_m)} ({cfg.near_km:g}–{cfg.mid_km:g} km)", opp)
    else:
        add("firsat", "proximity_far", f"Üsse {km(v.d_base_m)} (> {cfg.mid_km:g} km)", opp)

    # ---------------------------------------------------------------- Niyet göstergeleri: ne yapıyor
    add("niyet", "intent_base", "Başlangıç (gösterge yoksa niyet bilinmiyor)", cfg.intent_base, [ref])
    k = v.kinematics
    if k is None:
        add("niyet", "untracked", "Hareket kaydı yok (kayıtsız araç)", w.untracked)
    else:
        if k.approaching:
            add("niyet", "approaching", f"Üsse yaklaşıyor ({dec(k.closing_mps)} m/s)", w.approaching)
        if k.leaving:
            add("niyet", "leaving", f"Üsten uzaklaşıyor ({dec(abs(k.closing_mps))} m/s)", w.leaving)
    contradicted, confirmed = identity_reports_for(v, reports)
    if contradicted:
        ids = [r.report_id for r in contradicted]
        add(
            "niyet",
            "identity_contradicted",
            f"Aldatma göstergesi: kanıtla çelişen kimlik/dost iddiası ({', '.join(ids)})",
            w.identity_contradicted,
            ev + ids,
        )
    elif confirmed:
        ids = [r.report_id for r in confirmed]
        add(
            "niyet",
            "identity_confirmed",
            f"Kanıtla tutarlı dost kimliği ({', '.join(ids)})",
            w.identity_confirmed,
            ev + ids,
        )
    elif loose:
        add(
            "niyet",
            "identity_contradicted_frame",
            f"Kare çevresinde kanıtla çelişen kimlik iddiası ({', '.join(loose)})",
            w.identity_contradicted_frame,
            ev + loose,
        )
    return f


def dimension_score(factors: list[RiskFactor], dim: str) -> int:
    return int(max(0, min(100, sum(x.points for x in factors if x.dimension == dim))))
