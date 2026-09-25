"""TEST-ONLY detector: back-projects the track points at capture time into pixel space.

Lets the pipeline run end to end without a model. The class is unknown by construction.
Never used in the demo.
"""

from __future__ import annotations

from pathlib import Path

from sentinel.data.repository import Repository
from sentinel.domain.models import Detection
from sentinel.geo.georef import GeoReferencer


class OracleDetector:
    name = "oracle"

    def __init__(self, repo: Repository, vehicle_m: tuple[float, float] = (4.5, 2.0)):
        self.repo = repo
        self.vehicle_m = vehicle_m

    def detect(self, image_path: Path) -> list[Detection]:
        image_id = Path(image_path).stem
        meta = self.repo.meta[image_id]
        georef = GeoReferencer(meta)
        ids, pos = self.repo.tracks_at(meta.capture_min)
        w_px = self.vehicle_m[0] / georef.m_per_px()
        h_px = self.vehicle_m[1] / georef.m_per_px()
        dets: list[Detection] = []
        for _tid, (lat, lon) in sorted(zip(ids, pos, strict=True)):
            if not georef.contains(float(lat), float(lon)):
                continue
            cx, cy = georef.latlon_to_pixel(float(lat), float(lon))
            dets.append(
                Detection(
                    det_id=f"D{len(dets) + 1}",
                    label="unknown",
                    conf=1.0,
                    x=cx - w_px / 2,
                    y=cy - h_px / 2,
                    w=w_px,
                    h=h_px,
                )
            )
        return dets
