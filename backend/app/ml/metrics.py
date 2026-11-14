"""Evaluation metrics. Everything here is computed from predictions on held-out data; nothing is
hard-coded. Rates come with Wilson 95% intervals so small test sets cannot masquerade as proof."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from sklearn.metrics import roc_auc_score


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _r(x: float | None) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def binary_report(y_true: Sequence[int], y_pred: Sequence[int]) -> dict:
    y = np.asarray(y_true).astype(int)
    p = np.asarray(y_pred).astype(int)
    tp, fp = int(((p == 1) & (y == 1)).sum()), int(((p == 1) & (y == 0)).sum())
    fn, tn = int(((p == 0) & (y == 1)).sum()), int(((p == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
    return {
        "n": int(len(y)), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": _r((tp + tn) / len(y)) if len(y) else None, "accuracy_ci95": wilson(tp + tn, len(y)),
        "precision": _r(prec), "recall": _r(rec), "recall_ci95": wilson(tp, tp + fn), "f1": _r(f1),
        "false_positive_rate": _r(fp / (fp + tn)) if fp + tn else None, "fpr_ci95": wilson(fp, fp + tn),
        "false_negative_rate": _r(fn / (fn + tp)) if fn + tp else None, "fnr_ci95": wilson(fn, fn + tp),
    }


def auroc(y_true: Sequence[int], scores: Sequence[float]) -> float | None:
    y = np.asarray(y_true).astype(int)
    if len(np.unique(y)) < 2:
        return None
    return _r(roc_auc_score(y, np.asarray(scores, dtype=float)))


def ece(y_true: Sequence[int], probs: Sequence[float], bins: int = 10) -> dict:
    """Expected calibration error + reliability bins for P(defect)."""
    y = np.asarray(y_true).astype(float)
    p = np.asarray(probs, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    out, total = [], 0.0
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= edges[i + 1])
        if m.sum() == 0:
            continue
        conf, acc = float(p[m].mean()), float(y[m].mean())
        total += m.sum() / len(p) * abs(conf - acc)
        out.append({"bin": f"{edges[i]:.1f}-{edges[i+1]:.1f}", "n": int(m.sum()), "mean_predicted": round(conf, 4), "observed_rate": round(acc, 4)})
    return {"ece": round(float(total), 4), "bins": out}


def triage_report(y_true: Sequence[int], probs: Sequence[float], t_low: float, t_high: float) -> dict:
    """Three-way decision: pass (p<=t_low), defective (p>=t_high), else human review."""
    y = np.asarray(y_true).astype(int)
    p = np.asarray(probs, dtype=float)
    auto_pass, auto_fail = p <= t_low, p >= t_high
    review = ~(auto_pass | auto_fail)
    n = len(y)
    escaped = int((auto_pass & (y == 1)).sum())  # defective parts auto-passed
    overkill = int((auto_fail & (y == 0)).sum())  # good parts auto-rejected
    n_auto = int((~review).sum())
    return {
        "n": n, "t_low": round(float(t_low), 4), "t_high": round(float(t_high), 4),
        "auto_pass": int(auto_pass.sum()), "auto_defective": int(auto_fail.sum()), "sent_to_review": int(review.sum()),
        "review_rate": _r(review.sum() / n) if n else None,
        "auto_decision_accuracy": _r(1 - (escaped + overkill) / n_auto) if n_auto else None,
        "auto_decision_accuracy_ci95": wilson(n_auto - escaped - overkill, n_auto),
        "escaped_defects": escaped, "escape_rate_of_defects": _r(escaped / max(1, int((y == 1).sum()))),
        "escape_rate_ci95": wilson(escaped, int((y == 1).sum())),
        "false_rejects": overkill, "false_reject_rate_of_good": _r(overkill / max(1, int((y == 0).sum()))),
        "false_reject_ci95": wilson(overkill, int((y == 0).sum())),
    }


def pixel_report(gt: np.ndarray, pred: np.ndarray) -> dict:
    gt, pred = gt.astype(bool).ravel(), pred.astype(bool).ravel()
    tp, fp, fn = int((gt & pred).sum()), int((~gt & pred).sum()), int((gt & ~pred).sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return {"pixel_precision": _r(prec), "pixel_recall": _r(rec),
            "pixel_f1": _r(2 * tp / (2 * tp + fp + fn)) if tp + fp + fn else None,
            "iou": _r(tp / (tp + fp + fn)) if tp + fp + fn else None}


def multiclass_report(y_true: Sequence[str], y_pred: Sequence[str], classes: Sequence[str]) -> dict:
    y, p = np.asarray(y_true), np.asarray(y_pred)
    per = {}
    for c in classes:
        tp, fp, fn = int(((p == c) & (y == c)).sum()), int(((p == c) & (y != c)).sum()), int(((p != c) & (y == c)).sum())
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        per[c] = {"support": int((y == c).sum()), "precision": _r(prec), "recall": _r(rec), "recall_ci95": wilson(tp, tp + fn),
                  "f1": _r(2 * tp / (2 * tp + fp + fn)) if 2 * tp + fp + fn else None}
    f1s = [v["f1"] for v in per.values() if v["f1"] is not None and v["support"] > 0]
    conf = [[int(((y == a) & (p == b)).sum()) for b in classes] for a in classes]
    return {"n": int(len(y)), "accuracy": _r(float((y == p).mean())) if len(y) else None, "accuracy_ci95": wilson(int((y == p).sum()), len(y)),
            "macro_f1": _r(float(np.mean(f1s))) if f1s else None, "per_class": per, "confusion": {"labels": list(classes), "matrix": conf}}
