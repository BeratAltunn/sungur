"""Which reports concern a given frame (space + time)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sentinel.config import ReportsCfg
from sentinel.data.repository import Repository
from sentinel.domain.models import Claim, FieldReport
from sentinel.geo.zones import zone_display


@dataclass
class FrameContext:
    """What the verifier needs to know about the frame being evaluated."""

    image_id: str
    capture_min: int
    zone: str
    center: tuple[float, float]
    half_diag_m: float
    matched_tracks: list[str] = field(default_factory=list)
    labels_by_track: dict[str, str] = field(default_factory=dict)


@dataclass
class RelevantReport:
    report: FieldReport
    claim: Claim
    relevance: str
    dist_to_frame_m: float | None = None


def select_relevant(
    repo: Repository,
    claims: dict[str, Claim],
    ctx: FrameContext,
    cfg: ReportsCfg,
    window_min: int,
) -> list[RelevantReport]:
    t_hi = ctx.capture_min + (cfg.window_min if cfg.allow_after_capture else 0)
    t_lo = ctx.capture_min - cfg.window_min
    routes = {
        tid: [
            (p.lat, p.lon)
            for p in repo.track(tid).points
            if ctx.capture_min - window_min <= p.t_min <= ctx.capture_min
        ]
        for tid in ctx.matched_tracks
    }
    out: list[RelevantReport] = []
    for rep in repo.reports_between(t_lo, t_hi):
        claim = claims[rep.report_id]
        if claim.has_point:
            d_frame = float(repo.geo.distance_m(claim.lat, claim.lon, *ctx.center))
            if d_frame <= ctx.half_diag_m + cfg.radius_m:
                out.append(RelevantReport(rep, claim, f"kare çevresinde ({d_frame:.0f} m)", d_frame))
                continue
            near = _route_hit(repo, claim, routes, cfg.radius_m)
            if near:
                out.append(RelevantReport(rep, claim, f"{near} rotası üzerinde", d_frame))
        elif claim.zone is not None:
            if claim.zone == ctx.zone:
                out.append(RelevantReport(rep, claim, f"bölge: {zone_display(claim.zone)}"))
        elif claim.is_noise:
            out.append(RelevantReport(rep, claim, "genel bağlam"))
    return out


def _route_hit(
    repo: Repository, claim: Claim, routes: dict[str, list[tuple[float, float]]], radius: float
) -> str | None:
    for tid, pts in routes.items():
        if not pts:
            continue
        arr = np.asarray(pts)
        if float(np.min(repo.geo.distance_m(claim.lat, claim.lon, arr[:, 0], arr[:, 1]))) <= radius:
            return tid
    return None
