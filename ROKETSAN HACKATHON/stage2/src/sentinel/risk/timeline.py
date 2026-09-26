"""A detected vehicle's score over time: the same per-vehicle rules re-applied at each point of its track, with the
kinematics and reports known at that moment. The last point (capture time) is the packet's own score, so the map and
the frame screen agree where they meet.

Between captures the convoy factor is left out: a convoy is defined among the vehicles of one frame, and there is no
frame between captures. The vehicle's class is the detector's (it does not change along the track).
"""

from __future__ import annotations

from sentinel.config import Settings
from sentinel.domain.models import ReportVerification, Track, VehicleEvidence, to_min
from sentinel.geo.geodesy import LocalFrame
from sentinel.geo.zones import ZoneIndex
from sentinel.risk.features import vehicle_factors
from sentinel.tracking.kinematics import compute_kinematics


def score_timeline(
    v: VehicleEvidence,
    track: Track,
    reports: list[ReportVerification],
    capture_min: int,
    geo: LocalFrame,
    zones: ZoneIndex,
    s: Settings,
) -> list[tuple[int, int]]:
    """[(t_min, score)] at every track point before capture, then (capture_min, the packet's score)."""
    out: list[tuple[int, int]] = []
    for p in track.points:
        if p.t_min >= capture_min:
            break
        at = v.model_copy(
            update={
                "lat": p.lat,
                "lon": p.lon,
                "d_base_m": zones.relation(p.lat, p.lon).d_m,
                "kinematics": compute_kinematics(track, p.t_min, geo, zones, s.tracking),
            }
        )
        known = [r for r in reports if to_min(r.time) <= p.t_min]  # a report counts from its own time on
        score = sum(f.points for f in vehicle_factors(at, known, set(), s.risk))
        out.append((p.t_min, max(0, min(100, score))))
    out.append((capture_min, v.score))
    return out
