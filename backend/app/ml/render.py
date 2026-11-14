"""Rendering of annotated images, heatmap overlays and thumbnails."""
from __future__ import annotations

import cv2
import numpy as np

from .imageops import to_bgr

SEV_BGR = {"critical": (72, 72, 235), "major": (40, 150, 240), "minor": (70, 200, 230)}


def encode_jpg(img: np.ndarray, quality: int = 90) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def thumbnail(img: np.ndarray, side: int = 320) -> bytes:
    h, w = img.shape[:2]
    f = side / max(h, w)
    small = cv2.resize(img, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else img
    return encode_jpg(small, 82)


def heatmap_rgba(heat: np.ndarray) -> bytes:
    """Transparent PNG overlay: colour = TURBO(heat), alpha grows with heat."""
    h8 = np.clip(heat * 255, 0, 255).astype(np.uint8)
    color = cv2.applyColorMap(h8, cv2.COLORMAP_TURBO)
    alpha = np.clip((heat - 0.12) / 0.5, 0, 1) * 200
    return encode_png(np.dstack([color, alpha.astype(np.uint8)]))


def annotate(img: np.ndarray, findings: list[dict], heat: np.ndarray | None = None) -> np.ndarray:
    out = to_bgr(img).copy()
    h, w = out.shape[:2]
    if heat is not None:
        color = cv2.applyColorMap(np.clip(heat * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_TURBO)
        a = (np.clip((heat - 0.12) / 0.5, 0, 1) * 0.45)[..., None]
        out = (out * (1 - a) + color * a).astype(np.uint8)
    t = max(1, int(round(max(h, w) / 420)))
    fs = max(0.4, max(h, w) / 1400)
    for i, f in enumerate(findings, 1):
        col = SEV_BGR.get(f["severity"]["level"], (200, 200, 200))
        if len(f.get("polygon") or []) >= 3:
            cv2.polylines(out, [np.array(f["polygon"], np.int32)], True, col, t, cv2.LINE_AA)
        x, y, bw, bh = f["bbox"]
        cv2.rectangle(out, (x, y), (x + bw, y + bh), col, t)
        label = f"{i}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, max(1, t))
        ty = y - 4 if y - th - 6 > 0 else y + bh + th + 4
        cv2.rectangle(out, (x, ty - th - 3), (x + tw + 6, ty + 3), col, -1)
        cv2.putText(out, label, (x + 3, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, (20, 20, 20), max(1, t), cv2.LINE_AA)
    return out
