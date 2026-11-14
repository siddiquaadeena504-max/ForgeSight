"""Training-free surface screening with classical computer vision (OpenCV).

Finds pixels that deviate from the local background statistics (blobs, stains, pores) and thin
dark/bright ridges (cracks, scratches). It knows nothing about the material, so it is a
*screening* detector: useful for surfacing candidates on any material, never sufficient on its own
to pass or fail a part. Its measured performance on public datasets is reported in the model
evaluation dashboard (and it is modest).
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from ..imageops import regions_from_mask, to_gray
from ..types import DetectorOutput, InspectionContext


class ClassicalDetector:
    kind = "classical"
    name = "classical_cv"
    version = "1.0"
    validated = False

    def __init__(self, k_sigma: float = 5.0, ridge_sigma: float = 6.0, work_side: int = 768, min_area_frac: float = 0.00015):
        self.k_sigma = k_sigma
        self.ridge_sigma = ridge_sigma
        self.work_side = work_side
        self.min_area_frac = min_area_frac

    def score_map(self, img_bgr: np.ndarray) -> np.ndarray:
        """Robust z-score map (float32, at working resolution)."""
        g = to_gray(img_bgr)
        h, w = g.shape
        f = min(1.0, self.work_side / max(h, w))
        if f < 1.0:
            g = cv2.resize(g, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        g = cv2.GaussianBlur(g, (0, 0), 1.0).astype(np.float32)
        side = max(g.shape)
        # 1) blob / stain residual against a large-scale background estimate
        k = max(15, (side // 12) | 1)
        bg = cv2.medianBlur(np.clip(g, 0, 255).astype(np.uint8), k if k % 2 else k + 1).astype(np.float32)
        resid = g - bg
        mad = np.median(np.abs(resid - np.median(resid))) * 1.4826 + 1e-3
        z_blob = np.abs(resid) / mad
        # 2) thin ridges via multi-scale black-hat / top-hat
        z_ridge = np.zeros_like(g)
        for r in (max(3, side // 160), max(5, side // 80)):
            ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            for op in (cv2.MORPH_BLACKHAT, cv2.MORPH_TOPHAT):
                rr = cv2.morphologyEx(g, op, ker)
                m = np.median(np.abs(rr - np.median(rr))) * 1.4826 + 1e-3
                z_ridge = np.maximum(z_ridge, (rr - np.median(rr)) / m * (self.k_sigma / self.ridge_sigma))
        z = np.maximum(z_blob, z_ridge)
        return cv2.GaussianBlur(z, (0, 0), 1.2)

    def predict(self, img_bgr: np.ndarray, ctx: InspectionContext | None = None) -> DetectorOutput:
        t0 = time.perf_counter()
        h, w = img_bgr.shape[:2]
        z = self.score_map(img_bgr)
        mask = (z > self.k_sigma).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        heat_small = np.clip(z / (2.5 * self.k_sigma), 0, 1)
        heat = cv2.resize(heat_small, (w, h), interpolation=cv2.INTER_LINEAR)
        mask_full = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
        regions = regions_from_mask(mask_full, heat, self.name, min_area=max(12, int(self.min_area_frac * h * w)), max_regions=40)
        # image score: fraction-weighted exceedance, squashed to 0..1
        area = sum(r.area_px for r in regions) / float(h * w)
        peak = max((r.score for r in regions), default=0.0)
        score = float(1 - np.exp(-(60 * area + 1.5 * peak))) if regions else 0.0
        return DetectorOutput(name=self.name, kind=self.kind, image_score=score, heatmap=heat, regions=regions,
                              model_version=self.version, validated=False, latency_ms=(time.perf_counter() - t0) * 1000)
