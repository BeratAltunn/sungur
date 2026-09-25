"""Kaggle team's model behind the agreed contract (PROJECT_DESIGN §4.2):

    predict(image_path) -> list[(label, conf, x, y, w, h)]   # px, top-left, Kaggle format

config.yaml → detector.kind: callable, detector.callable.target: "module.path:predict".
If the team ships a plain ultralytics `.pt`, use detector.kind: ultralytics instead.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

from sentinel.domain.models import Detection
from sentinel.perception.base import from_tuples


class CallableDetector:
    def __init__(self, target: str, class_map: dict[str, str] | None = None):
        module_name, _, func_name = target.partition(":")
        if not func_name:
            raise ValueError(f"callable target 'modul:fonksiyon' biçiminde olmalı, verilen: {target!r}")
        self._fn: Callable[[Path], list[tuple]] = getattr(importlib.import_module(module_name), func_name)
        self.class_map = class_map
        self.name = f"kaggle:{module_name}"

    def detect(self, image_path: Path) -> list[Detection]:
        return from_tuples(self._fn(Path(image_path)), self.class_map)
