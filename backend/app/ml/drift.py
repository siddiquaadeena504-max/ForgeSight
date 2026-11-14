"""Production drift monitoring: population stability index (PSI) of live input/score distributions
against a reference (validation-time quantiles, or the first window of production data)."""
from __future__ import annotations

import numpy as np


def psi_from_quantiles(ref_quantiles: list[float], values: list[float]) -> float | None:
    """ref_quantiles: 11 deciles edges (0..100%) of the reference distribution -> 10 equal-mass bins."""
    v = np.asarray(values, dtype=float)
    if len(v) < 20:
        return None
    edges = np.asarray(ref_quantiles, dtype=float)[1:-1]
    live = np.bincount(np.searchsorted(edges, v, side="right"), minlength=10) / len(v)
    ref = np.full(10, 0.1)
    live = np.clip(live, 1e-4, None)
    return round(float(np.sum((live - ref) * np.log(live / ref))), 4)


def psi_status(psi: float | None) -> str:
    if psi is None:
        return "insufficient_data"
    return "stable" if psi < 0.1 else "moderate_shift" if psi < 0.25 else "significant_shift"


def quantiles(values: list[float]) -> list[float]:
    return np.quantile(np.asarray(values, dtype=float), np.linspace(0, 1, 11)).round(5).tolist()
