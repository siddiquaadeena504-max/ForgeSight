"""Material suggestion: nearest prototype over frozen backbone features, with an 'unknown' reject
option. It is a convenience only: the operator's choice always wins."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from .detectors.patchcore import PatchCore


class MaterialIdentifier:
    def __init__(self, path: Path):
        d = torch.load(path, map_location="cpu", weights_only=True)
        self.materials: list[str] = d["materials"]
        self.centroids = d["centroids"].numpy()
        self.radius = np.array(d["radius"])
        self._pc = PatchCore()

    def suggest(self, img_bgr: np.ndarray) -> dict:
        f = self._pc.embed([img_bgr]).mean((1, 2)).cpu().numpy()[0]
        f = f / np.linalg.norm(f)
        d = np.linalg.norm(self.centroids - f[None], axis=1)
        k = int(d.argmin())
        known = bool(d[k] <= self.radius[k])
        return {"material": self.materials[k] if known else None, "known": known,
                "similarity": round(float(max(0.0, 1 - d[k] / (2 * self.radius[k]))), 3),
                "candidates": [{"material": m, "distance": round(float(x), 4)} for m, x in sorted(zip(self.materials, d), key=lambda t: t[1])],
                "method": "nearest prototype (MobileNetV2 features)"}
