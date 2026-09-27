"""Ultralytics YOLO detector.

Serves both as the temporary fallback (pretrained COCO / VisDrone weights) and as the loader
for the Kaggle team's `.pt` file: only `weights` and `class_map` change in config.yaml.
COCO has no `van`; that gap is reported as an uncertainty by the pipeline.
"""

from __future__ import annotations

from pathlib import Path

from sentinel.config import UltralyticsCfg
from sentinel.domain.models import Detection
from sentinel.perception.base import from_tuples


class UltralyticsDetector:
    def __init__(self, cfg: UltralyticsCfg, weights_path: Path):
        try:
            from ultralytics import YOLO  # heavy import, only when selected
        except ImportError as e:  # pragma: no cover - depends on optional extra
            raise RuntimeError("ultralytics kurulu değil: `pip install -e '.[detector]'`") from e
        self.cfg = cfg
        self.device = cfg.device or _auto_device()
        self.model = YOLO(str(weights_path))
        self.name = f"yolo:{Path(weights_path).stem}"
        self.has_van = "van" in {cfg.class_map.get(n, n) for n in self.model.names.values()}

    def detect(self, image_path: Path) -> list[Detection]:
        res = self.model.predict(
            str(image_path),
            imgsz=self.cfg.imgsz,
            conf=self.cfg.min_conf,
            device=self.device,
            agnostic_nms=self.cfg.agnostic_nms,
            verbose=False,
        )[0]
        names = self.model.names
        rows = []
        for (x1, y1, x2, y2), conf, cls in zip(
            res.boxes.xyxy.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist(), strict=True
        ):
            rows.append((names[int(cls)], conf, x1, y1, x2 - x1, y2 - y1))
        return from_tuples(rows, self.cfg.class_map)


def _auto_device() -> str:
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda:0"
    except ImportError:  # pragma: no cover
        pass
    return "cpu"
