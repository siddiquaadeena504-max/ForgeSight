"""Confidence calibration (Platt scaling) and review-band threshold selection."""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression


class Platt:
    """P(defect) = sigmoid(a * score + b), fit on a validation split."""

    def __init__(self, a: float = 1.0, b: float = 0.0):
        self.a, self.b = a, b

    @classmethod
    def fit(cls, scores, labels) -> "Platt":
        x = np.asarray(scores, dtype=float).reshape(-1, 1)
        y = np.asarray(labels).astype(int)
        if len(np.unique(y)) < 2:
            raise ValueError("Calibration needs both good and defective validation samples")
        lr = LogisticRegression(C=1e3, class_weight="balanced", max_iter=1000).fit(x, y)
        return cls(float(lr.coef_[0, 0]), float(lr.intercept_[0]))

    def __call__(self, scores):
        z = self.a * np.asarray(scores, dtype=float) + self.b
        return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))

    def to_dict(self) -> dict:
        return {"type": "platt", "a": self.a, "b": self.b}

    @classmethod
    def from_dict(cls, d: dict) -> "Platt":
        return cls(d["a"], d["b"])


def select_review_band(probs, labels, max_escape: float = 0.0, max_false_reject: float = 0.0, margin: float = 0.5) -> tuple[float, float]:
    """Pick (t_low, t_high) on validation data.

    t_low : largest threshold such that the share of validation defects with p <= t_low is <= max_escape
    t_high: smallest threshold such that the share of validation goods with p >= t_high is <= max_false_reject
    `margin` (0..1) then widens the band toward the observed extremes to leave headroom for
    distribution shift; anything between the two goes to human review.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels).astype(int)
    d, g = np.sort(p[y == 1]), np.sort(p[y == 0])
    k = int(np.floor(max_escape * len(d)))
    lowest_defect = d[k] if len(d) else 1.0
    k = int(np.floor(max_false_reject * len(g)))
    highest_good = g[len(g) - 1 - k] if len(g) else 0.0
    # pass only below the lowest tolerated defect, fail only above the highest tolerated good
    t_low = lowest_defect - 1e-6
    t_high = highest_good + 1e-6
    if t_low > t_high:  # classes separate on validation: keep a review band between them
        lo, hi = t_high, t_low
        mid = (lo + hi) / 2
        t_low, t_high = mid - margin * (mid - lo), mid + margin * (hi - mid)
    return float(np.clip(t_low, 0, 1)), float(np.clip(t_high, 0, 1))
