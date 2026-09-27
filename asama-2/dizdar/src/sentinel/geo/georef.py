"""Pixel ↔ lat/lon for a nadir frame given its 4 corner coordinates.

Bilinear interpolation over the corners; for axis-aligned frames this reduces to the
organizer's linear formula:
    lon = TL.lon + (cx/W)·(TR.lon − TL.lon),  lat = TL.lat + (cy/H)·(BL.lat − TL.lat)
"""

from __future__ import annotations

import numpy as np

from sentinel.domain.models import ImageMeta
from sentinel.geo.geodesy import LocalFrame


class GeoReferencer:
    def __init__(self, meta: ImageMeta, width_px: int | None = None, height_px: int | None = None):
        self.meta = meta
        self.W = width_px or meta.width_px
        self.H = height_px or meta.height_px
        c = meta.corner_coordinates
        # (lat, lon) arrays
        self._tl = np.array(c.top_left, dtype=float)
        self._tr = np.array(c.top_right, dtype=float)
        self._bl = np.array(c.bottom_left, dtype=float)
        self._br = np.array(c.bottom_right, dtype=float)
        center = (self._tl + self._tr + self._bl + self._br) / 4
        self._frame = LocalFrame(float(center[0]), float(center[1]))

    # ---------------------------------------------------------------- forward
    def _bilinear(self, u, v):
        u = np.asarray(u, dtype=float)[..., None]
        v = np.asarray(v, dtype=float)[..., None]
        return (
            (1 - u) * (1 - v) * self._tl + u * (1 - v) * self._tr + (1 - u) * v * self._bl + u * v * self._br
        )

    def pixel_to_latlon(self, px, py):
        p = self._bilinear(np.asarray(px) / self.W, np.asarray(py) / self.H)
        lat, lon = p[..., 0], p[..., 1]
        if np.ndim(lat) == 0:
            return float(lat), float(lon)
        return lat, lon

    # ---------------------------------------------------------------- inverse
    def latlon_to_pixel(self, lat: float, lon: float, iters: int = 8) -> tuple[float, float]:
        """Newton iteration on (u, v); exact after 1 step for affine frames."""
        tx, ty = self._frame.to_local(lat, lon)
        target = np.array([float(tx), float(ty)])
        uv = np.array([0.5, 0.5])
        for _ in range(iters):
            p = self._bilinear(uv[0], uv[1])
            x, y = self._frame.to_local(p[0], p[1])
            r = np.array([float(x), float(y)]) - target
            if np.hypot(*r) < 1e-6:
                break
            J = np.empty((2, 2))
            eps = 1e-6
            for k in range(2):
                d = uv.copy()
                d[k] += eps
                pd = self._bilinear(d[0], d[1])
                xd, yd = self._frame.to_local(pd[0], pd[1])
                J[:, k] = (np.array([float(xd), float(yd)]) - np.array([float(x), float(y)])) / eps
            uv = uv - np.linalg.solve(J, r)
        return float(uv[0] * self.W), float(uv[1] * self.H)

    # ---------------------------------------------------------------- geometry
    def center(self) -> tuple[float, float]:
        lat, lon = self.pixel_to_latlon(self.W / 2, self.H / 2)
        return float(lat), float(lon)

    def polygon(self) -> list[tuple[float, float]]:
        """Corners as (lat, lon) in TL, TR, BR, BL order."""
        return [tuple(map(float, p)) for p in (self._tl, self._tr, self._br, self._bl)]

    def size_m(self) -> tuple[float, float]:
        f = self._frame
        w = float(f.distance_m(*self._tl, *self._tr))
        h = float(f.distance_m(*self._tl, *self._bl))
        return w, h

    def m_per_px(self) -> float:
        w, h = self.size_m()
        return (w / self.W + h / self.H) / 2

    def contains(self, lat: float, lon: float, margin_px: float = 0.0) -> bool:
        px, py = self.latlon_to_pixel(lat, lon)
        return -margin_px <= px <= self.W + margin_px and -margin_px <= py <= self.H + margin_px

    def half_diagonal_m(self) -> float:
        w, h = self.size_m()
        return float(np.hypot(w, h) / 2)
