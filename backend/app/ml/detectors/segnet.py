"""Supervised defect segmentation: MobileNetV2 encoder (ImageNet transfer) + FPN-style decoder.

One network gives localization (mask), classification (per-pixel class) and an image-level score.
It is trained per material on pixel-labelled data (see scripts/benchmarks.py).
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..backbones import MobileNetV2, get_device, mobilenetv2_imagenet, preprocess_batch
from ..imageops import regions_from_mask
from ..types import DetectorOutput, InspectionContext


class SegNet(nn.Module):
    TAPS = (3, 6, 13, 17)

    def __init__(self, num_classes: int, pretrained: bool = True, width: int = 64):
        super().__init__()
        self.encoder = mobilenetv2_imagenet(pretrained)
        chans = [MobileNetV2.TAPS[t][0] for t in self.TAPS]
        self.lateral = nn.ModuleList([nn.Conv2d(c, width, 1) for c in chans])
        self.smooth = nn.ModuleList(
            [nn.Sequential(nn.Conv2d(width, width, 3, padding=1, bias=False), nn.BatchNorm2d(width), nn.ReLU(inplace=True)) for _ in chans]
        )
        self.head = nn.Sequential(
            nn.Conv2d(width, width, 3, padding=1, bias=False), nn.BatchNorm2d(width), nn.ReLU(inplace=True),
            nn.Conv2d(width, num_classes + 1, 1),
        )

    def forward(self, x):
        feats = self.encoder.forward_taps(x, self.TAPS)
        p = None
        for i in range(len(feats) - 1, -1, -1):
            lat = self.lateral[i](feats[i])
            p = lat if p is None else lat + F.interpolate(p, size=lat.shape[-2:], mode="bilinear", align_corners=False)
            p = self.smooth[i](p)
        return F.interpolate(self.head(p), size=x.shape[-2:], mode="bilinear", align_corners=False)


class SegDetector:
    kind = "segmentation"

    def __init__(self, classes: list[str], input_size=(320, 320), name: str = "segnet", version: str | None = None, pretrained: bool = True):
        self.classes = list(classes)
        self.input_size = tuple(input_size)
        self.name = name
        self.version = version
        self.net = SegNet(len(classes), pretrained=pretrained).to(get_device())
        self.pixel_threshold = 0.5
        self.validated = False

    @torch.no_grad()
    def prob_maps(self, images: list[np.ndarray]) -> np.ndarray:
        """-> [N, K+1, h, w] softmax at network resolution."""
        self.net.eval()
        return torch.softmax(self.net(preprocess_batch(images, self.input_size)), 1).cpu().numpy()

    @staticmethod
    def image_score_from_prob(defect_prob: np.ndarray) -> float:
        """Mean of the top 0.1% defect probabilities (robust version of max)."""
        flat = np.sort(defect_prob.ravel())
        k = max(8, flat.size // 1000)
        return float(flat[-k:].mean())

    def predict(self, img_bgr: np.ndarray, ctx: InspectionContext | None = None) -> DetectorOutput:
        t0 = time.perf_counter()
        h, w = img_bgr.shape[:2]
        prob = self.prob_maps([img_bgr])[0]
        defect = 1.0 - prob[0]
        score = self.image_score_from_prob(defect)
        heat = cv2.resize(defect.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        cls_map = cv2.resize(prob[1:].argmax(0).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
        cls_prob = np.stack([cv2.resize(p.astype(np.float32), (w, h)) for p in prob[1:]])
        regions = regions_from_mask(heat > self.pixel_threshold, heat, self.name, min_area=max(6, int(0.00005 * h * w)))
        for r in regions:
            votes = np.bincount(cls_map[r.mask], minlength=len(self.classes))
            k = int(votes.argmax())
            r.defect_type = self.classes[k]
            r.type_confidence = float(cls_prob[k][r.mask].mean() / max(heat[r.mask].mean(), 1e-6))
            r.type_confidence = float(np.clip(r.type_confidence, 0, 1))
            r.type_source = "model"
        return DetectorOutput(
            name=self.name, kind=self.kind, image_score=score, heatmap=heat, regions=regions,
            model_version=self.version, validated=self.validated, latency_ms=(time.perf_counter() - t0) * 1000,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"classes": self.classes, "input_size": self.input_size, "state": self.net.state_dict(), "pixel_threshold": self.pixel_threshold}, path)

    @classmethod
    def load(cls, path: Path, name: str = "segnet", version: str | None = None) -> "SegDetector":
        d = torch.load(path, map_location="cpu", weights_only=True)
        m = cls(d["classes"], d["input_size"], name=name, version=version, pretrained=False)
        m.net.load_state_dict(d["state"])
        m.net.eval()
        m.pixel_threshold = d.get("pixel_threshold", 0.5)
        return m
