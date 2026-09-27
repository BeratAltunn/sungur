"""File cache around any detector so the demo never depends on live inference.

The cache directory is keyed by detector name + a fingerprint of its inference settings, so changing
e.g. the confidence floor or NMS mode never silently reuses stale boxes. With `inner=None` the cache
is read-only: the product keeps working from precomputed detections when the model cannot be loaded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sentinel.domain.models import Detection
from sentinel.perception.base import Detector


def fingerprint(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:8]


class CachedDetector:
    def __init__(self, inner: Detector | None, cache_dir: Path, name: str, params: dict | None = None):
        self.inner = inner
        self.name = name
        self.dir = (
            Path(cache_dir) / f"{name.replace(':', '_').replace('/', '_')}__{fingerprint(params or {})}"
        )
        self.last_hit: bool = False

    @property
    def cache_only(self) -> bool:
        return self.inner is None

    def _path(self, image_path: Path) -> Path:
        return self.dir / f"{Path(image_path).stem}.json"

    def has(self, image_path: Path) -> bool:
        return self._path(image_path).exists()

    def detect(self, image_path: Path, refresh: bool = False) -> list[Detection]:
        p = self._path(image_path)
        if p.exists() and (not refresh or self.inner is None):
            self.last_hit = True
            return [Detection.model_validate(d) for d in json.loads(p.read_text(encoding="utf-8"))]
        if self.inner is None:
            raise RuntimeError(f"Model yüklenemedi ve {Path(image_path).stem} için önbellekte tespit yok")
        self.last_hit = False
        dets = self.inner.detect(image_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([d.model_dump() for d in dets], indent=1), encoding="utf-8")
        return dets
