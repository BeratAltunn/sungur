"""Raw file → domain models. Only this module knows the on-disk format, so a schema change in
the official package is absorbed here. Validation errors carry file + row for quick triage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from sentinel.domain.models import Base, FieldReport, ImageMeta, Track, TrackPoint, Zone, to_min


class DataError(RuntimeError):
    pass


def load_image_meta(path: Path) -> dict[str, ImageMeta]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.items() if isinstance(raw, dict) else ((r["image_id"], r) for r in raw)
    out: dict[str, ImageMeta] = {}
    for image_id, rec in items:
        try:
            out[image_id] = ImageMeta.model_validate({**rec, "image_id": image_id})
        except ValidationError as e:
            raise DataError(f"{path.name}: {image_id}: {e}") from e
    return out


def load_zones(path: Path) -> tuple[Base, list[Zone]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        return Base.model_validate(raw["base"]), [Zone.model_validate(z) for z in raw["zones"]]
    except (KeyError, ValidationError) as e:
        raise DataError(f"{path.name}: {e}") from e


def load_tracks(path: Path) -> dict[str, Track]:
    df = pd.read_csv(path, dtype={"track_id": str, "time": str})
    missing = {"track_id", "time", "lat", "lon"} - set(df.columns)
    if missing:
        raise DataError(f"{path.name}: eksik sütun(lar) {sorted(missing)}")
    df["t_min"] = df["time"].map(to_min)
    tracks: dict[str, Track] = {}
    for tid, g in df.sort_values(["track_id", "t_min"]).groupby("track_id", sort=True):
        pts = tuple(
            TrackPoint(t_min=int(t), lat=float(a), lon=float(b))
            for t, a, b in zip(g["t_min"], g["lat"], g["lon"], strict=True)
        )
        tracks[str(tid)] = Track(track_id=str(tid), points=pts)
    return tracks


def load_reports(path: Path) -> list[FieldReport]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i, rec in enumerate(raw):
        try:
            rid = rec.get("report_id") or rec.get("id") or f"R{i:03d}"
            out.append(FieldReport.model_validate({**rec, "report_id": rid}))
        except ValidationError as e:
            raise DataError(f"{path.name}: satır {i}: {e}") from e
    return out
