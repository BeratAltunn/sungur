"""Zone lookup and base-relative position."""

from __future__ import annotations

from dataclasses import dataclass

from sentinel.domain.models import Base, Zone
from sentinel.geo.geodesy import LocalFrame, angle_diff, compass8

# Display names (data uses ASCII names).
ZONE_DISPLAY = {
    "Kuzey Yolu": "Kuzey Yolu",
    "Kuzeydogu Kavsagi": "Kuzeydoğu Kavşağı",
    "Dogu Yolu": "Doğu Yolu",
    "Guneydogu Yerlesimi": "Güneydoğu Yerleşimi",
    "Guney Kapisi Yaklasimi": "Güney Kapısı Yaklaşımı",
    "Guneybati Yolu": "Güneybatı Yolu",
    "Bati Yerlesimi": "Batı Yerleşimi",
    "Kuzeybati Yolu": "Kuzeybatı Yolu",
}


def zone_display(name: str) -> str:
    return ZONE_DISPLAY.get(name, name)


@dataclass(frozen=True)
class BaseRelation:
    d_m: float
    bearing_deg: float
    direction: str


class ZoneIndex:
    """Zones are sectors around the base: a point belongs to the zone whose centre bearing is
    angularly closest (frames sit on 1.6–5.3 km rings, so nearest-centre would misassign the inner ring).
    """

    def __init__(self, base: Base, zones: list[Zone], frame: LocalFrame):
        self.base = base
        self.zones = zones
        self.frame = frame
        self._bearings = [(z.name, frame.bearing_from_origin(*z.center)) for z in zones]

    def relation(self, lat: float, lon: float) -> BaseRelation:
        d = float(self.frame.dist_to_origin_m(lat, lon))
        b = self.frame.bearing_from_origin(lat, lon)
        return BaseRelation(d_m=d, bearing_deg=b, direction=compass8(b))

    def zone_of(self, lat: float, lon: float) -> str:
        b = self.frame.bearing_from_origin(lat, lon)
        return min(self._bearings, key=lambda nb: angle_diff(nb[1], b))[0]

    def names(self) -> list[str]:
        return [z.name for z in self.zones]
