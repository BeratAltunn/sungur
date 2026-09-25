"""Build the configured detector (one config line switches models).

If the model cannot be loaded (missing package, missing weights), fall back to its read-only detection
cache so the product and the demo keep working; `load_error` explains why.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sentinel.config import Settings
from sentinel.data.repository import Repository
from sentinel.perception.base import Detector
from sentinel.perception.cache import CachedDetector
from sentinel.perception.oracle import OracleDetector

log = logging.getLogger(__name__)


def _name_and_params(settings: Settings) -> tuple[str, dict]:
    cfg = settings.detector
    if cfg.kind == "ultralytics":
        u = cfg.ultralytics
        params = {"imgsz": u.imgsz, "min_conf": u.min_conf, "nms": u.agnostic_nms, "map": u.class_map}
        return f"yolo:{Path(u.weights).stem}", params
    return f"kaggle:{(cfg.callable.target or '').partition(':')[0]}", {"target": cfg.callable.target}


def build_detector(settings: Settings, repo: Repository) -> Detector:
    cfg = settings.detector
    if cfg.kind == "oracle":
        return OracleDetector(repo, cfg.oracle_vehicle_m)

    name, params = _name_and_params(settings)
    inner: Detector | None = None
    try:
        if cfg.kind == "ultralytics":
            from sentinel.perception.fallback import UltralyticsDetector

            weights = settings.path(cfg.ultralytics.weights)
            if not weights.exists():
                raise FileNotFoundError(f"ağırlık dosyası yok: {weights}")
            inner = UltralyticsDetector(cfg.ultralytics, weights)
        elif cfg.kind == "callable":
            from sentinel.perception.kaggle_model import CallableDetector

            if not cfg.callable.target:
                raise ValueError("detector.callable.target boş")
            inner = CallableDetector(cfg.callable.target, cfg.ultralytics.class_map)
    except (ImportError, RuntimeError, OSError, ValueError, AttributeError) as e:
        det = CachedDetector(None, settings.path(cfg.cache_dir), name, params)
        if not det.dir.exists():
            raise RuntimeError(f"Detektör yüklenemedi ({e}) ve önbellek de yok: {det.dir}") from e
        log.warning("Detektör yüklenemedi (%s); önbellekteki tespitler kullanılıyor", e)
        det.load_error = str(e)  # type: ignore[attr-defined]
        return det

    if not cfg.cache:
        return inner
    return CachedDetector(inner, settings.path(cfg.cache_dir), name, params)
