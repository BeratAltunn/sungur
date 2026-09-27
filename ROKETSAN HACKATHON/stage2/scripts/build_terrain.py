"""Download the terrain tiles the main map drapes in 3D: elevation (DEM) + a satellite texture, for offline use.

    python scripts/build_terrain.py                  # area = every vehicle position + 100 m, from the data package
    python scripts/build_terrain.py --bbox 32.76,39.85,32.95,39.99 --no-texture

Writes web/public/terrain/{dem,texture}/{z}/{x}/{y}.* and manifest.json. Vite copies public/ into web/dist, so the
tiles are served by both `make dev-web` and `make app` with no API change. The web UI turns terrain on only when
manifest.json exists. Display only: the pipeline never reads elevation (pixel → coordinate assumes flat ground).
The area just contains every track point, frame and the base; the ground ends at its edge. Standard library only;
re-running skips tiles already on disk (delete web/public/terrain first when the area shrinks).

Sources (both free, attribution is carried in manifest.json and shown on the map):
  DEM      AWS Terrain Tiles, Terrarium encoding (SRTM/GMTED …, ~30 m here)
  texture  Sentinel-2 cloudless 2016 by EOX (CC BY 4.0, 10 m)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEM_ATTR = "Arazi: AWS Terrain Tiles (SRTM)"
TEXTURE_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg"
TEXTURE_ATTR = "Sentinel-2 cloudless 2016 © EOX (CC BY 4.0)"


def area_from_data(data_dir: Path, pad_km: float) -> tuple[float, float, float, float]:
    """Bounding box of every vehicle position (tracks), frame footprint and the base, padded (read straight from
    the package files)."""
    meta = json.loads((data_dir / "image_meta.json").read_text(encoding="utf-8"))
    base = json.loads((data_dir / "zones.json").read_text(encoding="utf-8"))["base"]
    with open(data_dir / "tracks.csv", encoding="utf-8", newline="") as f:
        pts = [[float(r["lat"]), float(r["lon"])] for r in csv.DictReader(f)]
    pts += [p for m in meta.values() for p in m["corner_coordinates"].values()] + [[base["lat"], base["lon"]]]
    lat0 = sum(p[0] for p in pts) / len(pts)
    dlat, dlon = pad_km / 111.32, pad_km / (111.32 * math.cos(math.radians(lat0)))
    return (
        min(p[1] for p in pts) - dlon,
        min(p[0] for p in pts) - dlat,
        max(p[1] for p in pts) + dlon,
        max(p[0] for p in pts) + dlat,
    )


def tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def tile_lonlat(x: int, y: int, z: int) -> tuple[float, float]:
    n = 2**z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def tiles(bbox: tuple[float, float, float, float], zmin: int, zmax: int):
    w, s, e, n = bbox
    for z in range(zmin, zmax + 1):
        x0, y0 = tile_xy(w, n, z)
        x1, y1 = tile_xy(e, s, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def fetch(url: str, dest: Path) -> int:
    if dest.exists() and dest.stat().st_size > 0:
        return 0
    req = urllib.request.Request(url, headers={"User-Agent": "nobetci-terrain/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            break
        except OSError:
            if attempt == 2:
                raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return len(body)


def download(name: str, url: str, ext: str, out: Path, bbox, zmin: int, zmax: int) -> None:
    jobs = [
        (url.format(z=z, x=x, y=y), out / name / str(z) / str(x) / f"{y}.{ext}")
        for z, x, y in tiles(bbox, zmin, zmax)
    ]
    with ThreadPoolExecutor(8) as pool:
        sizes = list(pool.map(lambda j: fetch(*j), jobs))
    total = sum(f.stat().st_size for _, f in jobs)
    print(
        f"✓ {name}: {len(jobs)} karo (z{zmin}–{zmax}), {sum(1 for s in sizes if s)} yeni, {total / 1e6:.1f} MB"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--data",
        type=Path,
        default=Path(os.environ.get("SENTINEL_DATA_DIR", ROOT.parent / "stage2_dev_data")),
    )
    ap.add_argument("--bbox", help="W,S,E,N (derece); verilmezse veri paketinden hesaplanır")
    ap.add_argument("--pad-km", type=float, default=0.1)
    ap.add_argument("--min-zoom", type=int, default=9)
    ap.add_argument(
        "--dem-max-zoom",
        type=int,
        default=11,
        help="11 ≈ 60 m (genel bakış için yeterli); 12 ≈ 30 m, ~3× boyut",
    )
    ap.add_argument("--texture-max-zoom", type=int, default=14, help="10 m görüntü için 14")
    ap.add_argument("--no-texture", action="store_true", help="yalnızca DEM; doku DEM'den renklendirilir")
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "public" / "terrain")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # Windows consoles (cp1254) cannot print ✓
    bbox = tuple(float(v) for v in a.bbox.split(",")) if a.bbox else area_from_data(a.data, a.pad_km)
    if len(bbox) != 4:
        ap.error("--bbox W,S,E,N biçiminde olmalı")
    bbox = tuple(round(v, 5) for v in bbox)
    print(f"Alan: {bbox}")
    download("dem", DEM_URL, "png", a.out, bbox, a.min_zoom, a.dem_max_zoom)
    manifest = {
        "dem": {
            "bounds": bbox,
            "minzoom": a.min_zoom,
            "maxzoom": a.dem_max_zoom,
            "encoding": "terrarium",
            "attribution": DEM_ATTR,
        },
        "texture": None,
    }
    if not a.no_texture:
        download("texture", TEXTURE_URL, "jpg", a.out, bbox, a.min_zoom, a.texture_max_zoom)
        manifest["texture"] = {
            "bounds": bbox,
            "minzoom": a.min_zoom,
            "maxzoom": a.texture_max_zoom,
            "ext": "jpg",
            "attribution": TEXTURE_ATTR,
        }
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"✓ {a.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
