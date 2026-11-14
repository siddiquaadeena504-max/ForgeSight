"""Inspection engine: quality gate -> profile-selected detectors -> region fusion -> typing ->
severity -> three-way decision (pass / review / defective).

Design rules enforced here:
 * a profile chooses its detectors; no single model is assumed to cover every material;
 * an automatic PASS or DEFECTIVE needs a decision rule that was validated on held-out data for
   that profile; everything else is routed to human review with the reason spelled out;
 * observed facts (location, size, scores) are kept separate from knowledge-base hypotheses.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .calibration import Platt
from .detectors.classical import ClassicalDetector
from .imageops import bbox_iou, to_gray
from .knowledge import cause_hypotheses, defect_category, defect_label, recommended_action
from .quality import assess_quality
from .severity import estimate_severity
from .types import DetectorOutput, InspectionContext, Region

PRIORITY = {"segmentation": 5, "reference": 4, "detection": 3, "anomaly": 2, "classical": 1}
GENERIC_PROFILE = {
    "key": "generic_screening", "name": "Generic surface screening (unvalidated)", "requires_reference": False,
    "detectors": [{"type": "classical"}], "decision": {"mode": "screening", "validated": False, "image_level_validated": False},
}
DEFAULT_POLICY = {"allow_unvalidated_pass": False, "review_on_quality_warn": False, "disagreement_delta": 0.6}


@dataclass
class EngineResult:
    summary: dict[str, Any]  # JSON-serializable inspection record
    findings: list[dict[str, Any]]
    heatmap: np.ndarray | None  # float32 0..1
    regions: list[Region] = field(default_factory=list)


class ModelRegistry:
    """Loads and caches detector instances from the model store (<dir>/<name>/<version>/)."""

    def __init__(self, models_dir: Path):
        self.dir = Path(models_dir)
        self._cache: dict[str, Any] = {}
        self._lock = threading.Lock()

    def card(self, name: str, version: str) -> dict | None:
        p = self.dir / name / version / "card.json"
        return json.loads(p.read_text()) if p.exists() else None

    def get(self, spec: dict):
        if spec["type"] == "session":  # in-memory detector fitted on operator-supplied reference footage
            from ..services import live_sessions

            det = live_sessions.get(spec["id"])
            if det is None:
                raise LookupError("The reference-learning session has expired; learn the reference again")
            return det
        key = json.dumps({k: spec.get(k) for k in ("type", "model", "version", "params")}, sort_keys=True)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = self._load(spec)
            return self._cache[key]

    def invalidate(self):
        with self._lock:
            self._cache.clear()

    def _load(self, spec: dict):
        t = spec["type"]
        if t == "classical":
            return ClassicalDetector(**(spec.get("params") or {}))
        name, version = spec["model"], spec["version"]
        base = self.dir / name / version
        if t == "patchcore":
            from .detectors.patchcore import PatchCore
            det = PatchCore.load(base / "model.pt", name=name, version=version)
        elif t == "segnet":
            from .detectors.segnet import SegDetector
            det = SegDetector.load(base / "model.pt", name=name, version=version)
        elif t == "refdiff":
            from .detectors.refdiff import ReferenceDiffDetector
            det = ReferenceDiffDetector.load(base / "model.pt", name=name, version=version)
        elif t == "yolo":
            from .detectors.yolo import YoloDetector
            det = YoloDetector(base / "weights.pt", name=name, version=version, **(spec.get("params") or {}))
        else:
            raise ValueError(f"Unknown detector type '{t}'")
        card = self.card(name, version) or {}
        det.validated = bool(card.get("metrics"))
        return det


def _heuristic_type(region: Region, gray: np.ndarray) -> str:
    """Shape/intensity description for regions no trained classifier has named. Not a diagnosis."""
    x, y, w, h = region.bbox
    (_, _), (rw, rh), _ = cv2.minAreaRect(np.array(region.polygon, dtype=np.int32)) if len(region.polygon) >= 3 else ((0, 0), (w, h), 0)
    long_side, short_side = max(rw, rh, 1), max(min(rw, rh), 1)
    fill = region.area_px / max(1.0, long_side * short_side)
    if long_side / short_side >= 3.5 or (fill < 0.35 and long_side > 25):
        return "linear_mark"
    pad = max(4, int(0.5 * max(w, h)))
    H, W = gray.shape
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
    patch = gray[y0:y1, x0:x1].astype(np.float32)
    inside = region.mask[y0:y1, x0:x1] if region.mask is not None else np.zeros(patch.shape, bool)
    if inside.any() and (~inside).any():
        delta = float(patch[inside].mean() - patch[~inside].mean())
    else:
        delta = 0.0
    if region.area_px / float(H * W) > 0.01 and abs(delta) < 25:
        return "blotch"
    return "dark_spot" if delta < 0 else "bright_spot"


def _location(cx: float, cy: float, w: int, h: int) -> str:
    col = ["left", "centre", "right"][min(2, int(3 * cx / w))]
    row = ["top", "middle", "bottom"][min(2, int(3 * cy / h))]
    return "centre" if (row, col) == ("middle", "centre") else f"{row}-{col}"


def _merge_regions(outputs: list[DetectorOutput]) -> list[Region]:
    """Cross-detector fusion: overlapping regions become one finding carried by the most specific detector."""
    items = [(PRIORITY.get(o.kind, 0), o, r) for o in outputs for r in o.regions]
    items.sort(key=lambda t: (-t[0], -t[2].score))
    merged: list[Region] = []
    for _, o, r in items:
        hit = None
        for m in merged:
            if o.name in m.sources:
                continue
            overlap = bbox_iou(m.bbox, r.bbox) > 0.2
            if not overlap and m.mask is not None and r.mask is not None:
                inter = int((m.mask & r.mask).sum())
                overlap = inter > 0.3 * min(m.area_px, r.area_px)
            if overlap:
                hit = m
                break
        if hit is not None:
            hit.sources.append(o.name)
            hit.extra.setdefault("scores", {})[o.name] = round(r.score, 4)
        else:
            r.sources = [o.name]
            r.extra.setdefault("scores", {})[o.name] = round(r.score, 4)
            r.extra["kind"] = o.kind
            r.extra["validated"] = o.validated
            merged.append(r)
    return merged


class InspectionEngine:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def inspect(self, img_bgr: np.ndarray, material_key: str, profile: dict | None = None, reference_bgr: np.ndarray | None = None,
                mm_per_pixel: float | None = None, policy: dict | None = None) -> EngineResult:
        t_start = time.perf_counter()
        profile = profile or GENERIC_PROFILE
        policy = {**DEFAULT_POLICY, **(policy or {})}
        mm_per_pixel = mm_per_pixel or profile.get("mm_per_pixel")
        h, w = img_bgr.shape[:2]
        gray = to_gray(img_bgr)
        quality = assess_quality(img_bgr)
        ctx = InspectionContext(material_key, profile, reference_bgr, mm_per_pixel)

        outputs: list[DetectorOutput] = []
        errors: list[str] = []
        for spec in profile.get("detectors", []):
            try:
                outputs.append(self.registry.get(spec).predict(img_bgr, ctx))
            except Exception as exc:  # a broken model must never silently look like "no defects"
                errors.append(f"{spec.get('model') or spec['type']}: {type(exc).__name__}: {exc}")

        regions = _merge_regions(outputs)
        findings = [self._finding(r, gray, material_key, mm_per_pixel, profile) for r in regions]
        findings.sort(key=lambda f: ({"critical": 0, "major": 1, "minor": 2}[f["severity"]["level"]], -f["confidence"]))
        decision = self._decide(profile, outputs, findings, quality, errors, policy, reference_bgr is not None)

        heats = [o.heatmap for o in outputs if o.heatmap is not None]
        heatmap = np.mean(heats, axis=0).astype(np.float32) if heats else None
        summary = {
            "profile_key": profile.get("key"), "profile_name": profile.get("name"), "material": material_key,
            "image": {"width": w, "height": h}, "quality": quality, "decision": decision, "mm_per_pixel": mm_per_pixel,
            "detectors": [{"name": o.name, "kind": o.kind, "model_version": o.model_version, "validated": o.validated,
                           "image_score": None if o.image_score is None else round(o.image_score, 5), "regions": len(o.regions),
                           "latency_ms": round(o.latency_ms, 1), **({"note": o.meta["skipped"]} if o.meta.get("skipped") else {})} for o in outputs],
            "errors": errors, "processing_ms": round((time.perf_counter() - t_start) * 1000, 1),
        }
        return EngineResult(summary=summary, findings=findings, heatmap=heatmap, regions=regions)

    # ------------------------------------------------------------------------------------------
    def _finding(self, r: Region, gray: np.ndarray, material_key: str, mm_per_pixel: float | None, profile: dict) -> dict:
        h, w = gray.shape
        if r.type_source != "model":
            r.defect_type, r.type_source, r.type_confidence = _heuristic_type(r, gray), "heuristic", None
        pts = np.array(r.polygon, dtype=np.int32)
        if len(pts) >= 3:
            (cx, cy), (rw, rh), _ = cv2.minAreaRect(pts)
        else:
            x, y, bw, bh = r.bbox
            cx, cy, rw, rh = x + bw / 2, y + bh / 2, bw, bh
        length_px, width_px = float(max(rw, rh, 1)), float(max(min(rw, rh), 1))
        dims = {"length_px": round(length_px, 1), "width_px": round(width_px, 1), "area_px": int(r.area_px), "calibrated": bool(mm_per_pixel)}
        if mm_per_pixel:
            dims.update({"length_mm": round(length_px * mm_per_pixel, 3), "width_mm": round(width_px * mm_per_pixel, 3),
                         "area_mm2": round(r.area_px * mm_per_pixel**2, 4)})
        area_ratio = r.area_px / float(h * w)
        sev = estimate_severity(r.defect_type, area_ratio, length_px / float(max(h, w)), dims.get("length_mm"), profile.get("severity"))
        kind = r.extra.get("kind")
        basis = {"segmentation": "model_probability", "reference": "model_probability", "detection": "model_probability",
                 "anomaly": "anomaly_strength", "classical": "screening_heuristic"}.get(kind, "screening_heuristic")
        return {
            "defect_type": r.defect_type, "label": defect_label(r.defect_type), "category": defect_category(r.defect_type),
            "type_source": r.type_source, "type_confidence": None if r.type_confidence is None else round(r.type_confidence, 4),
            "confidence": round(float(r.score), 4), "confidence_basis": basis, "bbox": list(r.bbox), "polygon": r.polygon,
            "centroid": [round(float(cx), 1), round(float(cy), 1)], "location": _location(cx, cy, w, h), "area_ratio": round(area_ratio, 6),
            "dimensions": dims, "severity": sev, "sources": r.sources, "detector_scores": r.extra.get("scores", {}),
            "agreement": len(r.sources), "class_probs": r.extra.get("class_probs"),
            "cause_hypotheses": cause_hypotheses(r.defect_type, material_key),
            "recommended_action": recommended_action(r.defect_type, sev["level"], r.type_source),
        }

    def _decide(self, profile: dict, outputs: list[DetectorOutput], findings: list[dict], quality: dict, errors: list[str], policy: dict,
                has_reference: bool) -> dict:
        d = profile.get("decision") or {"mode": "screening"}
        mode = d.get("mode", "screening")
        reasons: list[str] = []
        p_defect: float | None = None
        per_detector: dict[str, float] = {}
        outcome = "review"
        scores = {o.name: o.image_score for o in outputs if o.image_score is not None}

        if mode == "fusion":
            missing = [f for f in d["features"] if f not in scores]
            if missing:
                reasons.append(f"Required detector output missing ({', '.join(missing)}); cannot apply the validated decision rule.")
            else:
                z = sum(c * scores[f] for c, f in zip(d["coef"], d["features"])) + d["intercept"]
                p_defect = float(1 / (1 + np.exp(-np.clip(z, -40, 40))))
                for spec in profile["detectors"]:
                    if spec.get("calibration") and spec["model"] in scores:
                        per_detector[spec["model"]] = round(float(Platt.from_dict(spec["calibration"])(scores[spec["model"]])), 4)
                if p_defect <= d["t_low"]:
                    outcome = "pass"
                    reasons.append(f"Calibrated defect probability {p_defect:.3f} is below the validated pass threshold {d['t_low']:.3f}.")
                elif p_defect >= d["t_high"]:
                    outcome = "defective"
                    reasons.append(f"Calibrated defect probability {p_defect:.3f} is above the validated reject threshold {d['t_high']:.3f}.")
                else:
                    reasons.append(f"Calibrated defect probability {p_defect:.3f} lies inside the review band ({d['t_low']:.3f}-{d['t_high']:.3f}).")
                if len(per_detector) >= 2 and max(per_detector.values()) - min(per_detector.values()) >= policy["disagreement_delta"] and outcome != "review":
                    outcome = "review"
                    reasons.append("Detectors disagree strongly (" + ", ".join(f"{k}: {v:.2f}" for k, v in per_detector.items()) + ").")
        elif mode == "regions":
            skipped = [f"{o.name}: {o.meta['skipped']}" for o in outputs if o.meta.get("skipped")]
            if profile.get("requires_reference") and not has_reference:
                reasons.append("This profile compares against a golden reference image and none was supplied.")
            elif skipped:
                reasons.append("Inspection could not be carried out - " + "; ".join(skipped) + ".")
            elif findings:
                thr = d.get("region_confident", 0.9)
                strong = [f for f in findings if f["confidence"] >= thr and f["type_source"] == "model"]
                if strong:
                    outcome = "defective"
                    reasons.append(f"{len(strong)} finding(s) with model confidence >= {thr:.2f} (defect-level detection validated on held-out data).")
                else:
                    reasons.append(f"Findings present but none reaches the confident threshold {thr:.2f}.")
            elif d.get("image_level_validated") or policy["allow_unvalidated_pass"]:
                outcome = "pass"
                reasons.append("No findings." + ("" if d.get("image_level_validated") else " (Pass allowed by policy although defect-free images were never validated.)"))
            else:
                reasons.append("No findings, but this profile has never been validated on defect-free samples, so an automatic PASS is not permitted.")
        else:  # screening
            if findings:
                reasons.append(f"{len(findings)} candidate region(s) from the unvalidated screening detector need human confirmation.")
            elif policy["allow_unvalidated_pass"]:
                outcome = "pass"
                reasons.append("No candidates found by the screening detector (pass allowed by policy; this profile is NOT validated).")
            else:
                reasons.append("No candidates found, but no validated model exists for this material/profile, so the part cannot be passed automatically.")

        if errors:
            outcome = "review"
            reasons.append("One or more detectors failed: " + "; ".join(errors))
        if quality["status"] == "fail" or (quality["status"] == "warn" and policy["review_on_quality_warn"]):
            bad = ", ".join(c["name"] for c in quality["checks"] if c["status"] != "ok")
            if outcome != "review":
                reasons.append(f"Automatic outcome '{outcome}' withheld: image quality gate {quality['status']} ({bad}).")
            else:
                reasons.append(f"Image quality gate {quality['status']} ({bad}).")
            outcome = "review"
        return {"outcome": outcome, "mode": mode, "p_defect": None if p_defect is None else round(p_defect, 4), "per_detector_probability": per_detector,
                "thresholds": {k: round(d[k], 4) for k in ("t_low", "t_high") if k in d}, "validated": bool(d.get("validated")),
                "image_level_validated": bool(d.get("image_level_validated")), "evidence": d.get("evidence"), "reasons": reasons}
