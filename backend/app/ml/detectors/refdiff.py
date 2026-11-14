"""Golden-reference comparison: align a defect-free template to the test image and localize
differences. Standard practice for printed/patterned products (PCBs, labels, printed textiles).
Optionally classifies each difference with a small CNN trained on (test, template) crop pairs.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn

from ..backbones import get_device
from ..imageops import regions_from_mask, to_gray
from ..types import DetectorOutput, InspectionContext, Region


class CropNet(nn.Module):
    """Small CNN over 2-channel (test, template) 64x64 crops."""

    def __init__(self, num_classes: int):
        super().__init__()

        def block(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                                 nn.Conv2d(o, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True), nn.MaxPool2d(2))

        self.features = nn.Sequential(block(2, 24), block(24, 48), block(48, 96), block(96, 128))
        self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.2), nn.Linear(128, num_classes))

    def forward(self, x):
        return self.head(self.features(x))


def crop_pair(test_g: np.ndarray, ref_g: np.ndarray, bbox, size: int = 64, context: float = 1.6) -> np.ndarray:
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    half = max(w, h) * context / 2 + 4
    x0, y0, x1, y1 = int(round(cx - half)), int(round(cy - half)), int(round(cx + half)), int(round(cy + half))
    H, W = test_g.shape
    pad = max(0, -x0, -y0, x1 - W, y1 - H)
    if pad:
        test_g = cv2.copyMakeBorder(test_g, pad, pad, pad, pad, cv2.BORDER_REFLECT_101)
        ref_g = cv2.copyMakeBorder(ref_g, pad, pad, pad, pad, cv2.BORDER_REFLECT_101)
        x0, y0, x1, y1 = x0 + pad, y0 + pad, x1 + pad, y1 + pad
    a = cv2.resize(test_g[y0:y1, x0:x1], (size, size), interpolation=cv2.INTER_AREA)
    b = cv2.resize(ref_g[y0:y1, x0:x1], (size, size), interpolation=cv2.INTER_AREA)
    return np.stack([a, b]).astype(np.float32) / 255.0


class ReferenceDiffDetector:
    kind = "reference"

    def __init__(self, diff_threshold: int = 60, min_area: int = 20, align: bool = True, merge_px: int = 5,
                 classes: list[str] | None = None, name: str = "reference_diff", version: str | None = "1.0", box_pad: int = 0):
        self.diff_threshold = diff_threshold
        self.min_area = min_area
        self.align = align
        self.merge_px = merge_px
        self.box_pad = box_pad
        self.drop_class = "false_alarm"
        self.max_diff_fraction = 0.15  # genuine DeepPCB test pairs: max 0.118; mismatched pairs: 1st percentile 0.185
        self.last_raw_fraction = 0.0
        self.classes = classes or []
        self.classifier: CropNet | None = None
        self.name = name
        self.version = version
        self.validated = False

    def _align(self, ref_g: np.ndarray, test_g: np.ndarray) -> np.ndarray:
        """Translation-only ECC alignment on a downscaled pair; falls back to identity."""
        try:
            f = min(1.0, 320 / max(test_g.shape))
            a = cv2.resize(test_g, None, fx=f, fy=f).astype(np.float32)
            b = cv2.resize(ref_g, None, fx=f, fy=f).astype(np.float32)
            warp = np.eye(2, 3, dtype=np.float32)
            crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 1e-4)
            _, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_TRANSLATION, crit, None, 5)
            warp[:, 2] /= f
            if np.abs(warp[:, 2]).max() > 0.08 * max(test_g.shape):
                return ref_g
            return cv2.warpAffine(ref_g, warp, (test_g.shape[1], test_g.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                  borderMode=cv2.BORDER_REPLICATE)
        except cv2.error:
            return ref_g

    def diff_mask(self, test_g: np.ndarray, ref_g: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a = cv2.GaussianBlur(test_g, (0, 0), 1.0)
        b = cv2.GaussianBlur(ref_g, (0, 0), 1.0)
        d = cv2.absdiff(a, b)
        mask = (d > self.diff_threshold).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        self.last_raw_fraction = float(mask.mean())  # before merging: used to detect a wrong / unregistered template
        if self.merge_px:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * self.merge_px + 1, 2 * self.merge_px + 1))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
        return mask, d

    def propose(self, test_g, ref_g, mask=None, heat=None) -> list[Region]:
        if mask is None:
            mask, d = self.diff_mask(test_g, ref_g)
            heat = np.clip(d.astype(np.float32) / 255.0, 0, 1)
        regions = regions_from_mask(mask, heat, self.name, min_area=self.min_area, max_regions=80)
        if self.box_pad:
            H, W = test_g.shape
            for r in regions:
                x, y, w, h = r.bbox
                x0, y0 = max(0, x - self.box_pad), max(0, y - self.box_pad)
                r.bbox = (x0, y0, min(W, x + w + self.box_pad) - x0, min(H, y + h + self.box_pad) - y0)
        return regions

    @torch.no_grad()
    def classify(self, test_g: np.ndarray, ref_g: np.ndarray, regions: list[Region]) -> None:
        if self.classifier is None or not regions:
            return
        self.classifier.eval()
        x = torch.from_numpy(np.stack([crop_pair(test_g, ref_g, r.bbox) for r in regions])).to(get_device())
        p = torch.softmax(self.classifier(x), 1).cpu().numpy()
        for r, pi in zip(regions, p):
            k = int(pi.argmax())
            r.defect_type, r.type_confidence, r.type_source = self.classes[k], float(pi[k]), "model"
            r.score = float(1.0 - pi[self.classes.index(self.drop_class)]) if self.drop_class in self.classes else float(pi[k])
            r.extra["class_probs"] = {c: round(float(v), 4) for c, v in zip(self.classes, pi)}

    def predict(self, img_bgr: np.ndarray, ctx: InspectionContext | None = None) -> DetectorOutput:
        t0 = time.perf_counter()
        if ctx is None or ctx.reference_bgr is None:
            return DetectorOutput(name=self.name, kind=self.kind, image_score=None, heatmap=None, regions=[],
                                  model_version=self.version, meta={"skipped": "no reference image supplied"})
        test_g = to_gray(img_bgr)
        ref_g = to_gray(ctx.reference_bgr)
        if ref_g.shape != test_g.shape:
            ref_g = cv2.resize(ref_g, (test_g.shape[1], test_g.shape[0]), interpolation=cv2.INTER_AREA)
        if self.align:
            ref_g = self._align(ref_g, test_g)
        mask, d = self.diff_mask(test_g, ref_g)
        heat = np.clip(d.astype(np.float32) / 255.0, 0, 1)
        differing = self.last_raw_fraction
        if differing > self.max_diff_fraction:
            # Not a defect pattern: the template is the wrong one or the pair is not registered.
            return DetectorOutput(name=self.name, kind=self.kind, image_score=None, heatmap=heat, regions=[], model_version=self.version,
                                  validated=self.validated, latency_ms=(time.perf_counter() - t0) * 1000,
                                  meta={"skipped": f"reference image does not match the inspected image ({differing * 100:.0f}% of pixels differ): "
                                                   "wrong template or misregistration"})
        regions = self.propose(test_g, ref_g, mask, heat)
        self.classify(test_g, ref_g, regions)
        regions = [r for r in regions if r.defect_type != self.drop_class]
        score = float(min(1.0, sum(r.area_px for r in regions) / (0.002 * mask.size))) if regions else 0.0
        return DetectorOutput(name=self.name, kind=self.kind, image_score=score, heatmap=heat, regions=regions,
                              model_version=self.version, validated=self.validated, latency_ms=(time.perf_counter() - t0) * 1000)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"diff_threshold": self.diff_threshold, "min_area": self.min_area, "align": self.align, "merge_px": self.merge_px,
                    "classes": self.classes, "box_pad": self.box_pad, "state": self.classifier.state_dict() if self.classifier else None}, path)

    @classmethod
    def load(cls, path: Path, name: str = "reference_diff", version: str | None = None) -> "ReferenceDiffDetector":
        d = torch.load(path, map_location="cpu", weights_only=True)
        m = cls(d["diff_threshold"], d["min_area"], d["align"], d["merge_px"], d["classes"], name=name, version=version, box_pad=d.get("box_pad", 0))
        if d["state"] is not None:
            m.classifier = CropNet(len(d["classes"])).to(get_device())
            m.classifier.load_state_dict(d["state"])
            m.classifier.eval()
        return m
