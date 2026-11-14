import numpy as np
import pytest

from app.ml import metrics as M
from app.ml.calibration import Platt, select_review_band
from app.ml.detectors.classical import ClassicalDetector
from app.ml.drift import psi_from_quantiles, psi_status, quantiles
from app.ml.knowledge import cause_hypotheses
from app.ml.pipeline import GENERIC_PROFILE, InspectionEngine, ModelRegistry
from app.ml.quality import assess_quality
from app.ml.severity import estimate_severity
from app.services.datasets import hamming, phash

from .conftest import texture


def test_binary_report_counts_and_rates():
    r = M.binary_report([1, 1, 1, 0, 0, 0, 0, 0], [1, 1, 0, 1, 0, 0, 0, 0])
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2, 1, 1, 4)
    assert r["precision"] == pytest.approx(0.6667, abs=1e-4) and r["recall"] == pytest.approx(0.6667, abs=1e-4)
    assert r["false_positive_rate"] == 0.2 and r["false_negative_rate"] == pytest.approx(0.3333, abs=1e-4)


def test_wilson_interval_is_honest_about_small_samples():
    lo, hi = M.wilson(50, 50)
    assert hi == 1.0 and lo < 0.94  # 50/50 correct does NOT demonstrate 99.9%
    lo, _ = M.wilson(5000, 5000)
    assert lo > 0.999


def test_auroc_and_ece():
    assert M.auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert M.auroc([1, 1], [0.1, 0.2]) is None  # undefined with one class
    e = M.ece([0, 0, 1, 1], [0.0, 0.0, 1.0, 1.0])
    assert e["ece"] == 0.0


def test_triage_report_counts_escapes_and_false_rejects():
    y = [0, 0, 0, 1, 1, 1]
    p = [0.05, 0.5, 0.95, 0.02, 0.5, 0.99]
    t = M.triage_report(y, p, 0.1, 0.9)
    assert t["auto_pass"] == 2 and t["auto_defective"] == 2 and t["sent_to_review"] == 2
    assert t["escaped_defects"] == 1 and t["false_rejects"] == 1


def test_multiclass_and_pixel_reports():
    r = M.multiclass_report(["a", "a", "b"], ["a", "b", "b"], ["a", "b"])
    assert r["accuracy"] == pytest.approx(0.6667, abs=1e-4) and r["confusion"]["matrix"] == [[1, 1], [0, 1]]
    gt = np.zeros((10, 10), bool); gt[:5] = True
    pr = np.zeros((10, 10), bool); pr[:5, :5] = True
    assert M.pixel_report(gt, pr)["iou"] == 0.5


def test_platt_and_review_band():
    rng = np.random.default_rng(0)
    s = np.concatenate([rng.normal(1, 0.3, 200), rng.normal(3, 0.3, 200)])
    y = np.array([0] * 200 + [1] * 200)
    pl = Platt.fit(s, y)
    p = pl(s)
    assert p[:200].mean() < 0.1 and p[200:].mean() > 0.9
    t_low, t_high = select_review_band(p, y)
    assert 0 <= t_low <= t_high <= 1
    assert (p[y == 1] <= t_low).sum() == 0 and (p[y == 0] >= t_high).sum() == 0  # zero validation escapes / false rejects
    with pytest.raises(ValueError):
        Platt.fit([1, 2, 3], [0, 0, 0])


def test_review_band_overlapping_classes_sends_overlap_to_review():
    p = np.array([0.1, 0.2, 0.6, 0.4, 0.8, 0.9])
    y = np.array([0, 0, 0, 1, 1, 1])
    t_low, t_high = select_review_band(p, y)
    assert t_low < 0.4 and t_high > 0.6


def test_quality_gate():
    assert assess_quality(texture(1))["status"] in ("ok", "warn")
    dark = np.full((300, 300, 3), 4, np.uint8)
    q = assess_quality(dark)
    assert q["status"] == "fail" and any(c["name"] in ("exposure", "contrast") and c["status"] == "fail" for c in q["checks"])
    tiny = texture(2, 64)
    assert assess_quality(tiny)["status"] == "fail"
    blown = np.full((300, 300, 3), 255, np.uint8); blown[:100] = texture(3, 300)[:100]
    assert any(c["name"] == "glare" and c["status"] != "ok" for c in assess_quality(blown)["checks"])


def test_severity_rules():
    assert estimate_severity("scratch", 0.0001, 0.01, None)["level"] == "minor"
    assert estimate_severity("scratch", 0.005, 0.01, None)["level"] == "major"
    assert estimate_severity("scratch", 0.05, 0.01, None)["level"] == "critical"
    assert estimate_severity("open", 0.00001, 0.001, None)["level"] == "critical"
    assert estimate_severity("crack", 0.00001, 0.001, None)["level"] == "major"  # structural floor
    assert estimate_severity("scratch", 0.0001, 0.01, 6.0)["level"] == "critical"  # calibrated length


def test_cause_hypotheses_only_for_named_defects():
    assert cause_hypotheses("crack", "ceramics")[0].startswith("Thermal shock")
    assert cause_hypotheses("crack", "custom")  # generic fallback
    assert cause_hypotheses("dark_spot", "metals") == []  # unclassified region -> no invented cause
    assert cause_hypotheses("anomaly", "metals") == []


def test_classical_detector_finds_obvious_defects_and_not_clean_texture():
    det = ClassicalDetector()
    clean = [len(det.predict(texture(s)).regions) for s in range(6)]
    assert sum(clean) <= 1
    blob = det.predict(texture(10, defect="blob"))
    assert blob.regions and blob.heatmap.shape == (256, 256)
    assert det.predict(texture(11, defect="scratch")).regions


def test_generic_profile_never_auto_passes_or_fails(tmp_path):
    eng = InspectionEngine(ModelRegistry(tmp_path))
    clean = eng.inspect(texture(1), "metals", GENERIC_PROFILE)
    assert clean.summary["decision"]["outcome"] == "review" and not clean.summary["decision"]["validated"]
    bad = eng.inspect(texture(10, defect="blob"), "metals", GENERIC_PROFILE)
    assert bad.summary["decision"]["outcome"] == "review"
    f = bad.findings[0]
    assert f["type_source"] == "heuristic" and f["cause_hypotheses"] == [] and f["confidence_basis"] == "screening_heuristic"
    assert f["dimensions"]["calibrated"] is False and "length_mm" not in f["dimensions"]
    relaxed = eng.inspect(texture(1), "metals", GENERIC_PROFILE, policy={"allow_unvalidated_pass": True})
    assert relaxed.summary["decision"]["outcome"] == "pass"
    cal = eng.inspect(texture(10, defect="blob"), "metals", GENERIC_PROFILE, mm_per_pixel=0.1)
    assert cal.findings[0]["dimensions"]["length_mm"] == pytest.approx(cal.findings[0]["dimensions"]["length_px"] * 0.1, abs=0.01)


def test_broken_detector_forces_review(tmp_path):
    eng = InspectionEngine(ModelRegistry(tmp_path))
    prof = {"key": "x", "detectors": [{"type": "patchcore", "model": "missing", "version": "1.0.0"}],
            "decision": {"mode": "fusion", "features": ["missing"], "coef": [1.0], "intercept": 0.0, "t_low": 0.2, "t_high": 0.8, "validated": True}}
    r = eng.inspect(texture(1), "metals", prof)
    assert r.summary["decision"]["outcome"] == "review" and r.summary["errors"]


def test_quality_failure_overrides_automatic_outcome(tmp_path):
    eng = InspectionEngine(ModelRegistry(tmp_path))
    r = eng.inspect(np.full((300, 300, 3), 3, np.uint8), "metals", GENERIC_PROFILE, policy={"allow_unvalidated_pass": True})
    assert r.summary["decision"]["outcome"] == "review"
    assert any("quality gate" in x for x in r.summary["decision"]["reasons"])


def test_psi():
    rng = np.random.default_rng(0)
    ref = quantiles(rng.normal(0, 1, 5000).tolist())
    assert psi_status(psi_from_quantiles(ref, rng.normal(0, 1, 500).tolist())) == "stable"
    assert psi_status(psi_from_quantiles(ref, rng.normal(1.5, 1, 500).tolist())) == "significant_shift"
    assert psi_from_quantiles(ref, [0.0] * 5) is None


def test_phash_near_duplicates():
    a = texture(5)
    assert hamming(phash(a), phash(a.copy())) == 0
    import cv2
    recompressed = cv2.imdecode(cv2.imencode(".jpg", a, [cv2.IMWRITE_JPEG_QUALITY, 70])[1], 1)
    assert hamming(phash(a), phash(recompressed)) <= 4
    assert hamming(phash(a), phash(texture(6, defect="blob"))) > 4
