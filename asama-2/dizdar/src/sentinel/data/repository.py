"""In-memory repository: loads the data files once and indexes tracks on a time grid.

~5.6k track points fit in a dense [tracks × time] array, so every spatio-temporal query is a
vectorised numpy expression. The interface is what a PostGIS-backed version would expose.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

import numpy as np

from sentinel.data import adapters
from sentinel.domain.models import FieldReport, ImageMeta, Track, TrackSnapshot, hhmm
from sentinel.geo.geodesy import LocalFrame
from sentinel.geo.zones import ZoneIndex


class Repository:
    STEP_MIN = 5

    def __init__(self, data_dir: Path, images_subdir: str = "images"):
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / images_subdir
        self.meta: dict[str, ImageMeta] = adapters.load_image_meta(self.data_dir / "image_meta.json")
        self.base, self.zones = adapters.load_zones(self.data_dir / "zones.json")
        self.tracks: dict[str, Track] = adapters.load_tracks(self.data_dir / "tracks.csv")
        self.reports: list[FieldReport] = adapters.load_reports(self.data_dir / "field_reports.json")
        self.geo = LocalFrame(self.base.lat, self.base.lon)
        self.zone_index = ZoneIndex(self.base, self.zones, self.geo)
        self._build_grid()

    # ---------------------------------------------------------------- index
    def _build_grid(self) -> None:
        t0 = min(t.t_start for t in self.tracks.values())
        t1 = max(t.t_end for t in self.tracks.values())
        self._t0 = t0
        self._times = np.arange(t0, t1 + self.STEP_MIN, self.STEP_MIN)
        self._ids = list(self.tracks)
        self._row = {tid: i for i, tid in enumerate(self._ids)}
        grid = np.full((len(self._ids), len(self._times), 2), np.nan)
        for i, tid in enumerate(self._ids):
            for p in self.tracks[tid].points:
                k = (p.t_min - t0) // self.STEP_MIN
                if 0 <= k < len(self._times) and (p.t_min - t0) % self.STEP_MIN == 0:
                    grid[i, k] = (p.lat, p.lon)
        self._grid = grid  # (lat, lon)

    @property
    def time_range(self) -> tuple[int, int]:
        return int(self._times[0]), int(self._times[-1])

    def _positions_at(self, t_min: float) -> np.ndarray:
        """[N, 2] lat/lon of all tracks at t (linear interpolation, NaN where not covered)."""
        f = (t_min - self._t0) / self.STEP_MIN
        if f < 0 or f > len(self._times) - 1:
            return np.full((len(self._ids), 2), np.nan)
        k0 = int(np.floor(f))
        a = f - k0
        if a < 1e-9:
            return self._grid[:, k0]
        k1 = min(k0 + 1, len(self._times) - 1)
        return (1 - a) * self._grid[:, k0] + a * self._grid[:, k1]

    # ---------------------------------------------------------------- queries
    def tracks_at(self, t_min: float) -> tuple[list[str], np.ndarray]:
        """Track ids covered at t and their [N, 2] lat/lon."""
        pos = self._positions_at(t_min)
        ok = ~np.isnan(pos[:, 0])
        return [tid for tid, m in zip(self._ids, ok, strict=True) if m], pos[ok]

    def position(self, track_id: str, t_min: float) -> tuple[float, float] | None:
        p = self._positions_at(t_min)[self._row[track_id]]
        return None if np.isnan(p[0]) else (float(p[0]), float(p[1]))

    def track(self, track_id: str) -> Track:
        return self.tracks[track_id]

    def tracks_near(self, lat: float, lon: float, t_min: float, radius_m: float) -> list[TrackSnapshot]:
        ids, pos = self.tracks_at(t_min)
        if not ids:
            return []
        d = self.geo.distance_m(lat, lon, pos[:, 0], pos[:, 1])
        out = [
            TrackSnapshot(
                track_id=tid,
                time=hhmm(t_min),
                lat=float(p[0]),
                lon=float(p[1]),
                dist_m=float(dd),
                d_base_m=float(self.geo.dist_to_origin_m(p[0], p[1])),
            )
            for tid, p, dd in zip(ids, pos, d, strict=True)
            if dd <= radius_m
        ]
        return sorted(out, key=lambda s: s.dist_m or 0.0)

    def passes_near(self, lat: float, lon: float, radius_m: float) -> dict[str, list[int]]:
        """Tracks that come within radius of the point at any recorded time → {track_id: [t_min, ...]}."""
        lat_g, lon_g = self._grid[..., 0], self._grid[..., 1]
        d = self.geo.distance_m(lat, lon, lat_g, lon_g)
        hit = np.nan_to_num(d, nan=np.inf) <= radius_m
        out: dict[str, list[int]] = {}
        for i, k in zip(*np.nonzero(hit), strict=True):
            out.setdefault(self._ids[i], []).append(int(self._times[k]))
        return out

    def reports_between(self, t0: float, t1: float) -> list[FieldReport]:
        return [r for r in self.reports if t0 <= r.t_min <= t1]

    def report(self, report_id: str) -> FieldReport:
        return self._reports_by_id[report_id]

    @cached_property
    def _reports_by_id(self) -> dict[str, FieldReport]:
        return {r.report_id: r for r in self.reports}

    def image_path(self, image_id: str) -> Path:
        for ext in (".jpg", ".jpeg", ".png"):
            p = self.images_dir / f"{image_id}{ext}"
            if p.exists():
                return p
        return self.images_dir / f"{image_id}.jpg"

    def frames(self, zone: str | None = None) -> list[ImageMeta]:
        out = sorted(self.meta.values(), key=lambda m: (m.capture_min, m.image_id))
        if zone is None:
            return out
        return [m for m in out if self.frame_zone(m.image_id) == zone]

    def frame_zone(self, image_id: str) -> str:
        c = self.meta[image_id].corner_coordinates
        lat = (c.top_left[0] + c.bottom_right[0]) / 2
        lon = (c.top_left[1] + c.bottom_right[1]) / 2
        return self.zone_index.zone_of(lat, lon)
