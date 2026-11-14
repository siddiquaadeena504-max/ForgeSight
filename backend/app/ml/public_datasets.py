"""Loaders + deterministic, leakage-checked splits for the public datasets used to validate the engine.

 - Magnetic Tile Surface Defects (Huang et al., "Saliency of magnetic tile surface defects")
 - DeepPCB (Tang et al.) - official trainval/test split
 - CrackForest (Shi et al., 2016)
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

DATA_ROOT = Path(os.environ.get("FS_EXTERNAL_DATA", Path(__file__).resolve().parents[3] / "data" / "external"))

MT_CLASSES = ["blowhole", "break", "crack", "fray", "uneven"]
PCB_CLASSES = ["open", "short", "mousebite", "spur", "copper", "pin-hole"]


@dataclass
class Sample:
    path: str
    label: str  # "good" or defect class
    mask_path: str | None = None
    ref_path: str | None = None
    boxes: list[tuple[int, int, int, int, str]] = field(default_factory=list)  # x, y, w, h, class
    split: str = ""
    group: str = ""

    def image(self) -> np.ndarray:
        return cv2.imread(self.path, cv2.IMREAD_COLOR)


def _bucket(key: str, seed: str) -> float:
    return int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def assign_split(key: str, seed: str = "fs-v1", val: float = 0.2, test: float = 0.2) -> str:
    """Deterministic hash split: the same group key always lands in the same split."""
    b = _bucket(key, seed)
    return "test" if b < test else "val" if b < test + val else "train"


def file_sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def drop_cross_split_duplicates(samples: list[Sample]) -> tuple[list[Sample], int]:
    """Exact-duplicate guard: if identical bytes appear in more than one split keep only the first."""
    seen: dict[str, str] = {}
    out, dropped = [], 0
    for s in samples:
        h = file_sha(s.path)
        if h in seen and seen[h] != s.split:
            dropped += 1
            continue
        seen.setdefault(h, s.split)
        out.append(s)
    return out, dropped


def load_magnetic_tile() -> list[Sample]:
    root = DATA_ROOT / "Magnetic-tile-defect-datasets"
    out = []
    for folder, label in [("MT_Free", "good"), ("MT_Blowhole", "blowhole"), ("MT_Break", "break"), ("MT_Crack", "crack"),
                          ("MT_Fray", "fray"), ("MT_Uneven", "uneven")]:
        for p in sorted((root / folder / "Imgs").glob("*.jpg")):
            m = p.with_suffix(".png")
            out.append(Sample(str(p), label, str(m) if m.exists() else None, group=p.stem, split=assign_split(f"{label}/{p.stem}")))
    return out


def mt_mask(s: Sample, shape: tuple[int, int] | None = None) -> np.ndarray:
    m = cv2.imread(s.mask_path, cv2.IMREAD_GRAYSCALE) if s.mask_path else None
    if m is None:
        img = cv2.imread(s.path, cv2.IMREAD_GRAYSCALE)
        m = np.zeros(img.shape[:2], np.uint8)
    m = (m > 127).astype(np.uint8)
    if s.label == "good":
        m[:] = 0
    return m


def load_deeppcb() -> list[Sample]:
    root = DATA_ROOT / "DeepPCB" / "PCBData"
    out = []
    for list_file, split in [("trainval.txt", "train"), ("test.txt", "test")]:
        for line in (root / list_file).read_text().split("\n"):
            if not line.strip():
                continue
            img_rel, ann_rel = line.split()
            stem = img_rel[:-4]
            boxes = []
            for row in (root / ann_rel).read_text().split("\n"):
                parts = row.replace(",", " ").split()
                if len(parts) == 5:
                    x1, y1, x2, y2, c = (int(v) for v in parts)
                    boxes.append((x1, y1, x2 - x1, y2 - y1, PCB_CLASSES[c - 1]))
            s = Sample(str(root / f"{stem}_test.jpg"), "defective", ref_path=str(root / f"{stem}_temp.jpg"), boxes=boxes,
                       split=split, group=img_rel.split("/")[0])
            if split == "train" and _bucket(os.path.basename(stem), "pcb-val") < 0.2:
                s.split = "val"
            out.append(s)
    return out


def load_crackforest() -> list[Sample]:
    root = DATA_ROOT / "CrackForest-dataset"
    out = []
    for p in sorted((root / "image").glob("*.jpg")):
        m = root / "groundTruth" / f"{p.stem}.mat"
        if m.exists():
            out.append(Sample(str(p), "crack", str(m), group=p.stem, split=assign_split(f"cfd/{p.stem}")))
    return out


def cfd_mask(s: Sample) -> np.ndarray:
    import scipy.io as sio

    seg = sio.loadmat(s.mask_path)["groundTruth"][0, 0]["Segmentation"]
    return (seg >= 2).astype(np.uint8)
