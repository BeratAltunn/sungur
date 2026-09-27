"""scripts/build_terrain.py: the tiles fetched are the right ones and the area just contains every vehicle."""

from __future__ import annotations

import csv
import importlib.util

from sentinel.config import PROJECT_ROOT, load_settings

_spec = importlib.util.spec_from_file_location("build_terrain", PROJECT_ROOT / "scripts" / "build_terrain.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)

DATA = load_settings().data_path  # the data package the system runs on
BASE = (32.85306, 39.92184)  # Merkez Us (lon, lat)


def test_tile_index_matches_slippy_map_convention():
    assert bt.tile_xy(0.0, 0.0, 1) == (1, 1)
    assert bt.tile_xy(-180.0, 85.0, 3) == (0, 0)
    # The tile found for the base contains it: its NW corner is west/north of it, the next tile's corner east/south.
    x, y = bt.tile_xy(*BASE, 12)
    (w, n), (e, s) = bt.tile_lonlat(x, y, 12), bt.tile_lonlat(x + 1, y + 1, 12)
    assert w <= BASE[0] < e and s < BASE[1] <= n


def test_area_barely_contains_every_vehicle():
    pad_km = 0.1
    w, s, e, n = bt.area_from_data(DATA, pad_km=pad_km)
    with open(DATA / "tracks.csv", encoding="utf-8", newline="") as f:
        pts = [(float(r["lon"]), float(r["lat"])) for r in csv.DictReader(f)]
    assert all(w < lon < e and s < lat < n for lon, lat in pts)
    # tight: each edge is only the pad away from the outermost vehicle (or frame corner)
    assert abs((min(lat for _, lat in pts) - s) * 111.32 - pad_km) < 0.01
    assert abs((n - max(lat for _, lat in pts)) * 111.32 - pad_km) < 0.01
