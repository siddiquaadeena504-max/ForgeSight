"""Rule-based severity estimate. Transparent by design: the rationale string states which rule fired.
Thresholds can be overridden per inspection profile (`severity` block)."""
from __future__ import annotations

from .knowledge import criticality

DEFAULT_RULES = {"area_major": 0.002, "area_critical": 0.02, "extent_major": 0.08, "extent_critical": 0.30,
                 "mm_major": 1.0, "mm_critical": 5.0, "critical_types": ["open", "short", "missing_component", "break"]}


def estimate_severity(defect_type: str, area_ratio: float, extent_ratio: float, length_mm: float | None, rules: dict | None = None) -> dict:
    r = {**DEFAULT_RULES, **(rules or {})}
    crit = criticality(defect_type)
    level, why = "minor", "small extent and area"
    if defect_type in r["critical_types"]:
        level, why = "critical", f"'{defect_type}' is listed as a functional/critical defect type for this profile"
    elif area_ratio >= r["area_critical"] or extent_ratio >= r["extent_critical"] or (length_mm is not None and length_mm >= r["mm_critical"]):
        level, why = "critical", "size exceeds the critical limit"
    elif area_ratio >= r["area_major"] or extent_ratio >= r["extent_major"] or (length_mm is not None and length_mm >= r["mm_major"]):
        level, why = "major", "size exceeds the major limit"
    if level == "minor" and crit >= 0.85:
        level, why = "major", "structural defect type: at least major regardless of size"
    score = min(1.0, 0.45 * crit + 0.35 * min(1.0, area_ratio / r["area_critical"]) + 0.20 * min(1.0, extent_ratio / r["extent_critical"]))
    return {"level": level, "score": round(score, 3), "rationale": f"Rule-based estimate: {why}."}
