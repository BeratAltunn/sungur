"""Equirectangular approximation around the base.

The organizer's data was generated with exactly this projection (111320 m/deg, cos(lat_base)),
so it reproduces their reference numbers 1:1. Error vs. true geodesic < 0.3% at 6 km.
"""

from __future__ import annotations

import math

import numpy as np

M_PER_DEG = 111_320.0
COMPASS8 = ("K", "KD", "D", "GD", "G", "GB", "B", "KB")
COMPASS8_LONG = {
    "K": "kuzey",
    "KD": "kuzeydoğu",
    "D": "doğu",
    "GD": "güneydoğu",
    "G": "güney",
    "GB": "güneybatı",
    "B": "batı",
    "KB": "kuzeybatı",
}


class LocalFrame:
    """Local metric frame (x = east, y = north) with the origin at (lat0, lon0)."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self.ky = M_PER_DEG
        self.kx = M_PER_DEG * math.cos(math.radians(lat0))

    def to_local(self, lat, lon):
        """Vectorised: scalars or arrays → (x_east, y_north) metres."""
        return (np.asarray(lon) - self.lon0) * self.kx, (np.asarray(lat) - self.lat0) * self.ky

    def to_latlon(self, x, y):
        return self.lat0 + np.asarray(y) / self.ky, self.lon0 + np.asarray(x) / self.kx

    def distance_m(self, lat1, lon1, lat2, lon2):
        dx = (np.asarray(lon2) - np.asarray(lon1)) * self.kx
        dy = (np.asarray(lat2) - np.asarray(lat1)) * self.ky
        return np.hypot(dx, dy)

    def dist_to_origin_m(self, lat, lon):
        x, y = self.to_local(lat, lon)
        return np.hypot(x, y)

    def bearing_from_origin(self, lat, lon) -> float:
        x, y = self.to_local(lat, lon)
        return bearing_deg(float(x), float(y))


def bearing_deg(dx: float, dy: float) -> float:
    """Compass bearing of a (east, north) vector, 0 = north, clockwise."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def compass8(bearing: float) -> str:
    return COMPASS8[int(((bearing % 360) + 22.5) // 45) % 8]


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings (deg)."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)
