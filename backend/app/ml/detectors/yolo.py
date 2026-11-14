"""Ultralytics YOLO adapter for supervised defect localization.

Used when a material has box-labelled data and a trained weights file is registered
(scripts/train_yolo.py exports a dataset and trains one). No weights ship with the platform.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..types import DetectorOutput, InspectionContext, Region


class YoloDetector:
    kind = "detection"

    def __init__(self, weights: Path, name: str = "yolo", version: str | None = None, conf: float = 0.25, imgsz: int = 640):
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.name, self.version, self.conf, self.imgsz = name, version, conf, imgsz
        self.validated = False

    def predict(self, img_bgr: np.ndarray, ctx: InspectionContext | None = None) -> DetectorOutput:
        t0 = time.perf_counter()
        res = self.model.predict(img_bgr, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        regions = []
        for box, conf, cls in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(), res.boxes.cls.cpu().numpy()):
            x1, y1, x2, y2 = (int(round(v)) for v in box)
            w, h = max(1, x2 - x1), max(1, y2 - y1)
            regions.append(Region(bbox=(x1, y1, w, h), polygon=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], area_px=w * h, score=float(conf),
                                  defect_type=str(res.names[int(cls)]), type_confidence=float(conf), type_source="model", sources=[self.name]))
        score = max((r.score for r in regions), default=0.0)
        return DetectorOutput(name=self.name, kind=self.kind, image_score=score, heatmap=None, regions=regions,
                              model_version=self.version, validated=self.validated, latency_ms=(time.perf_counter() - t0) * 1000)
