"""A detected vehicle's threat over time: the same capability–opportunity–intent rules (matrix + floors) re-applied
at each point of its track, with the kinematics and reports known at that moment. The last point (capture time) is
the packet's own assessment, so the map and the frame screen agree where they meet.

Between captures the convoy is left out: a convoy is defined among the vehicles of one frame, and there is no frame
between captures. The vehicle's class is the packet's (it does not change along the track).
"""

from __future__ import annotations

from sentinel.config import Settings
from sentinel.domain.models import ReportVerification, RiskLevel, Track, VehicleEvidence, to_min
from sentinel.geo.geodesy import LocalFrame
from sentinel.geo.zones import ZoneIndex
from sentinel.risk.features import loose_identity_reports
from sentinel.risk.scoring import assess_vehicle
from sentinel.tracking.kinematics import compute_kinematics


def score_timeline(
    v: VehicleEvidence,
    track: Track,
    reports: list[ReportVerification],
    capture_min: int,
    geo: LocalFrame,
    zones: ZoneIndex,
    s: Settings,
) -> list[tuple[int, int, RiskLevel]]:
    """[(t_min, ordering score, level)] at every track point before capture, then the packet's own at capture."""
    out: list[tuple[int, int, RiskLevel]] = []
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
        assess_vehicle(at, [at], known, {}, loose_identity_reports(known, [at]), s.risk)
        out.append((p.t_min, at.score, at.level))
    out.append((capture_min, v.score, v.level))
    return out
