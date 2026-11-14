"""Shared data structures for the inspection engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Region:
    """One localized irregularity. `mask` is a full-resolution boolean array (not serialized)."""

    bbox: tuple[int, int, int, int]  # x, y, w, h in original image pixels
    polygon: list[list[int]]  # outer contour [[x, y], ...]
    area_px: int
    score: float  # detector-native evidence strength, 0..1
    defect_type: str = "anomaly"
    type_confidence: float | None = None
    type_source: str = "none"  # "model" | "heuristic" | "none"
    sources: list[str] = field(default_factory=list)
    mask: np.ndarray | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectorOutput:
    name: str
    kind: str  # anomaly | segmentation | reference | classical | detection
    image_score: float | None  # raw image-level score (higher = more anomalous)
    heatmap: np.ndarray | None  # float32 HxW in 0..1 at original resolution
    regions: list[Region]
    model_version: str | None = None
    validated: bool = False
    latency_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class InspectionContext:
    material_key: str
    profile: dict[str, Any]
    reference_bgr: np.ndarray | None = None
    mm_per_pixel: float | None = None
