"""PatchCore-style anomaly detector (Roth et al., 2022), CPU-friendly variant.

Fit: extract locally-averaged mid-level features from *defect-free* images with a frozen
ImageNet backbone, keep a coreset of patch embeddings (memory bank).
Predict: distance of each test patch to its nearest memory-bank neighbour = anomaly map.

It needs only good samples, which is why it is the default learnable detector for new materials.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from ..backbones import get_device, load_backbone, preprocess_batch
from ..imageops import regions_from_mask
from ..types import DetectorOutput, InspectionContext


class PatchCore:
    kind = "anomaly"

    def __init__(self, backbone: str = "mobilenetv2", taps=(6, 13), input_size=(256, 256), name: str = "patchcore", version: str | None = None):
        self.backbone_name = backbone
        self.taps = tuple(taps)
        self.input_size = tuple(input_size)
        self.name = name
        self.version = version
        self.memory: torch.Tensor | None = None
        self.score_scale: float = 1.0  # distance that maps to heatmap value 1.0
        self.pixel_threshold: float | None = None  # raw distance; set at calibration time
        self.validated = False

    # ---- features -------------------------------------------------------------------------
    @torch.no_grad()
    def embed(self, images: list[np.ndarray]) -> torch.Tensor:
        """-> [N, H, W, C] patch embeddings on the finest tapped grid."""
        net = load_backbone(self.backbone_name, self.taps)
        x = preprocess_batch(images, self.input_size)
        feats = net(x)
        target = feats[0].shape[-2:]
        pooled = []
        for f in feats:
            f = F.avg_pool2d(f, 3, 1, 1)
            if f.shape[-2:] != target:
                f = F.interpolate(f, size=target, mode="bilinear", align_corners=False)
            pooled.append(f)
        return torch.cat(pooled, 1).permute(0, 2, 3, 1).contiguous()

    def embed_many(self, images: list[np.ndarray], batch: int = 16) -> torch.Tensor:
        return torch.cat([self.embed(images[i : i + batch]).cpu() for i in range(0, len(images), batch)])

    # ---- fit ------------------------------------------------------------------------------
    @staticmethod
    def _kcenter(x: torch.Tensor, n: int, seed: int = 0) -> torch.Tensor:
        """Greedy k-center coreset selection (indices)."""
        g = torch.Generator().manual_seed(seed)
        first = int(torch.randint(len(x), (1,), generator=g))
        idx = [first]
        dist = torch.cdist(x, x[first : first + 1]).squeeze(1)
        for _ in range(n - 1):
            nxt = int(torch.argmax(dist))
            idx.append(nxt)
            dist = torch.minimum(dist, torch.cdist(x, x[nxt : nxt + 1]).squeeze(1))
        return torch.tensor(idx)

    def fit_embeddings(self, emb: torch.Tensor, coreset: int = 4000, presample: int = 40000, seed: int = 0, method: str = "kcenter") -> None:
        patches = emb.reshape(-1, emb.shape[-1])
        g = torch.Generator().manual_seed(seed)
        if len(patches) > presample:
            patches = patches[torch.randperm(len(patches), generator=g)[:presample]]
        if len(patches) > coreset:
            patches = patches[self._kcenter(patches, coreset, seed)] if method == "kcenter" else patches[:coreset]  # already shuffled
        self.memory = patches.contiguous()

    def fit(self, good_images: list[np.ndarray], **kw) -> None:
        self.fit_embeddings(self.embed_many(good_images), **kw)

    # ---- predict --------------------------------------------------------------------------
    @torch.no_grad()
    def distance_maps(self, emb: torch.Tensor) -> np.ndarray:
        """[N,H,W,C] embeddings -> [N,H,W] nearest-neighbour distances."""
        assert self.memory is not None, "PatchCore is not fitted"
        dev = get_device()
        mem = self.memory.to(dev)
        n, h, w, c = emb.shape
        out = []
        for i in range(n):
            d = torch.cdist(emb[i].reshape(-1, c).to(dev), mem).min(dim=1).values
            out.append(d.reshape(h, w).cpu())
        return torch.stack(out).numpy()

    @staticmethod
    def image_score(dmap: np.ndarray) -> float:
        sm = cv2.GaussianBlur(dmap.astype(np.float32), (0, 0), 1.0)
        return float(sm.max())

    @staticmethod
    def full_map(dmap: np.ndarray, h: int, w: int) -> np.ndarray:
        full = cv2.resize(dmap.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        return cv2.GaussianBlur(full, (0, 0), max(1.0, 0.012 * max(h, w)))

    def predict(self, img_bgr: np.ndarray, ctx: InspectionContext | None = None) -> DetectorOutput:
        t0 = time.perf_counter()
        h, w = img_bgr.shape[:2]
        dmap = self.distance_maps(self.embed([img_bgr]))[0]
        score = self.image_score(dmap)
        full = self.full_map(dmap, h, w)
        heat = np.clip(full / max(self.score_scale, 1e-6), 0, 1)
        regions = []
        if self.pixel_threshold is not None:
            scale = float((ctx.profile or {}).get("threshold_scale", 1.0)) if ctx is not None else 1.0  # operator sensitivity (sessions)
            mask = full > self.pixel_threshold * scale
            regions = regions_from_mask(mask, heat, self.name, min_area=max(16, int(0.0004 * h * w)))
        return DetectorOutput(
            name=self.name, kind=self.kind, image_score=score, heatmap=heat, regions=regions,
            model_version=self.version, validated=self.validated, latency_ms=(time.perf_counter() - t0) * 1000,
        )

    # ---- persistence ----------------------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {"backbone": self.backbone_name, "taps": self.taps, "input_size": self.input_size, "memory": self.memory,
             "score_scale": self.score_scale, "pixel_threshold": self.pixel_threshold},
            path,
        )

    @classmethod
    def load(cls, path: Path, name: str = "patchcore", version: str | None = None) -> "PatchCore":
        d = torch.load(path, map_location="cpu", weights_only=True)
        m = cls(d["backbone"], d["taps"], d["input_size"], name=name, version=version)
        m.memory, m.score_scale, m.pixel_threshold = d["memory"], d["score_scale"], d["pixel_threshold"]
        return m
