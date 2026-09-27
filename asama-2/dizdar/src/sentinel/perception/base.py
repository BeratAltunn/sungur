"""Detector contract. Output mirrors the Kaggle submission format: label conf x y w h (px, top-left)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from sentinel.domain.models import Detection

VALID_LABELS = {"car", "van", "truck", "bus"}


@runtime_checkable
class Detector(Protocol):
    name: str

    def detect(self, image_path: Path) -> list[Detection]: ...


def from_tuples(rows: Iterable[tuple], class_map: dict[str, str] | None = None) -> list[Detection]:
    """[(label, conf, x, y, w, h), ...] → Detection list; unknown classes are dropped."""
    out: list[Detection] = []
    for label, conf, x, y, w, h in rows:
        lab = (class_map or {}).get(str(label), str(label))
        if lab not in VALID_LABELS:
            continue
        out.append(
            Detection(
                det_id=f"D{len(out) + 1}",
                label=lab,  # type: ignore[arg-type]
                conf=float(conf),
                x=float(x),
                y=float(y),
                w=float(w),
                h=float(h),
            )
        )
    return out
