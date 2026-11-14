"""Small image helpers shared by detectors."""
from __future__ import annotations

import cv2
import numpy as np

from .types import Region


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Unsupported or corrupt image data")
    return img


def to_gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def to_bgr(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img


def limit_size(img: np.ndarray, max_side: int = 2048) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return img, 1.0
    f = max_side / s
    return cv2.resize(img, (int(round(w * f)), int(round(h * f))), interpolation=cv2.INTER_AREA), f


def regions_from_mask(
    mask: np.ndarray,
    score_map: np.ndarray | None,
    source: str,
    min_area: int = 12,
    max_regions: int = 60,
    default_score: float = 1.0,
) -> list[Region]:
    """Connected components -> Region list (largest first, capped)."""
    mask_u8 = (mask > 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    out: list[Region] = []
    order = sorted(range(1, n), key=lambda i: -stats[i, cv2.CC_STAT_AREA])
    for i in order[: max_regions * 3]:
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x, y, w, h = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        comp = labels[y : y + h, x : x + w] == i
        cnts, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        # Keep the outline faithful (thin cracks!) but bounded: tighten epsilon until the polygon has at most ~160 points.
        eps = 0.6
        approx = cv2.approxPolyDP(c, eps, True)
        while len(approx) > 160:
            eps *= 1.6
            approx = cv2.approxPolyDP(c, eps, True)
        c = approx
        poly = [[int(p[0][0]) + x, int(p[0][1]) + y] for p in c]
        if score_map is not None:
            score = float(np.max(score_map[y : y + h, x : x + w][comp]))
        else:
            score = default_score
        full = np.zeros(mask.shape[:2], dtype=bool)
        full[y : y + h, x : x + w] = comp
        out.append(Region(bbox=(x, y, w, h), polygon=poly, area_px=area, score=float(np.clip(score, 0, 1)), sources=[source], mask=full))
        if len(out) >= max_regions:
            break
    return out


def bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0
