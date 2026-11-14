"""Image quality / lighting gate. A failed gate forces human review: the engine never passes or
fails a part from an image it cannot see properly."""
from __future__ import annotations

import cv2
import numpy as np

from .imageops import to_gray


def assess_quality(img_bgr: np.ndarray) -> dict:
    g = to_gray(img_bgr)
    h, w = g.shape
    f = 512 / max(h, w)
    gs = cv2.resize(g, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else g
    checks = []

    def add(name, value, status, message, unit=""):
        checks.append({"name": name, "value": round(float(value), 3), "unit": unit, "status": status, "message": message})

    min_side = min(h, w)
    add("resolution", min_side, "fail" if min_side < 96 else "warn" if min_side < 224 else "ok",
        f"{w}x{h} px" + (" - too small to resolve fine defects" if min_side < 224 else ""), "px")

    # Binarized / thresholded imagery (e.g. AOI line-scan) is bimodal by design: exposure and glare checks do not apply.
    extremes = float(((gs <= 40) | (gs >= 215)).mean())
    binary_like = extremes > 0.92 and float((gs <= 40).mean()) > 0.002 and float((gs >= 215).mean()) > 0.002
    mean = float(gs.mean())
    if binary_like:
        add("exposure", mean, "ok", "Binarized image (exposure checks not applicable)")
    else:
        st = "fail" if mean < 20 or mean > 238 else "warn" if mean < 45 or mean > 215 else "ok"
        add("exposure", mean, st, {"ok": "Mean brightness within range", "warn": "Image is rather dark/bright", "fail": "Severely under/over-exposed"}[st])
        clip = float((gs >= 252).mean())
        add("glare", clip * 100, "fail" if clip > 0.25 else "warn" if clip > 0.03 else "ok",
            f"{clip * 100:.1f}% saturated highlights" + (" - specular glare can hide or mimic defects" if clip > 0.03 else ""), "%")
        dark = float((gs <= 3).mean())
        add("shadow_clipping", dark * 100, "warn" if dark > 0.15 else "ok", f"{dark * 100:.1f}% crushed blacks", "%")

    std = float(gs.std())
    add("contrast", std, "fail" if std < 2.0 else "warn" if std < 6.0 else "ok",
        "Almost no signal in image" if std < 2 else "Low global contrast" if std < 6 else "Sufficient contrast")

    lap = float(cv2.Laplacian(gs, cv2.CV_64F).var())
    add("sharpness", lap, "fail" if lap < 1.5 else "warn" if lap < 12 else "ok",
        "Image appears out of focus" if lap < 1.5 else "Low high-frequency detail (smooth surface or soft focus)" if lap < 12 else "In focus")

    if not binary_like:
        illum = cv2.GaussianBlur(gs.astype(np.float32), (0, 0), max(gs.shape) / 6)
        ratio = float((np.percentile(illum, 98) + 1) / (np.percentile(illum, 2) + 1))
        add("lighting_uniformity", ratio, "warn" if ratio > 2.2 else "ok",
            "Strong illumination gradient across the part" if ratio > 2.2 else "Illumination reasonably uniform", "x")

    worst = "fail" if any(c["status"] == "fail" for c in checks) else "warn" if any(c["status"] == "warn" for c in checks) else "ok"
    n_warn = sum(c["status"] == "warn" for c in checks)
    score = 0.0 if worst == "fail" else max(0.4, 1.0 - 0.15 * n_warn)
    return {"status": worst, "score": round(score, 2), "width": w, "height": h, "checks": checks}
