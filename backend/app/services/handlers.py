"""Job handlers: video inspection and in-app PatchCore fitting from a managed dataset."""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter

import cv2
import numpy as np
from sqlalchemy import select

from ..config import get_settings
from ..ml import metrics as M
from ..ml.calibration import Platt, select_review_band
from ..ml.imageops import decode_image
from ..ml.render import encode_jpg
from ..models import Dataset, DatasetImage, ModelVersion, utcnow
from ..storage import get_storage
from .engine import get_registry
from .inspection import run_inspection
from .jobs import handler


@handler("video_inspection")
def video_inspection(db, job, progress):
    p = job.payload
    data = get_storage().get(p["storage_key"])
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(p.get("filename") or "v.mp4")[1] or ".mp4")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise ValueError("Video could not be decoded (unsupported container/codec)")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(fps * float(p.get("every_seconds", 1.0)))))
        max_frames = int(p.get("max_frames", 120))
        counts: Counter = Counter()
        idx = done = 0
        while done < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                insp, _ = run_inspection(db, image_bytes=encode_jpg(frame, 92), filename=f"{p.get('filename', 'video')}#frame{idx}", user_email=job.created_by,
                                         material_key=p.get("material_key"), profile_key=p.get("profile_key"), batch_id=p.get("batch_id"),
                                         product_id=p.get("product_id"), source="video", job_id=job.id, frame_index=idx)
                counts[insp.outcome] += 1
                done += 1
                progress(min(0.99, (idx + 1) / total) if total else 0.5, frames_inspected=done, outcomes=dict(counts))
            idx += 1
        cap.release()
        if done == 0:
            raise ValueError("No frames could be read from the video")
        return {"frames_inspected": done, "frames_total": total or idx, "fps": round(fps, 2), "sample_every_frames": step, "outcomes": dict(counts)}
    finally:
        os.unlink(path)
        get_storage().delete(p["storage_key"])


@handler("fit_patchcore")
def fit_patchcore(db, job, progress):
    """Fit an anomaly model on the defect-free TRAIN images of a dataset; calibrate on VAL; report on TEST.
    Test images are never used for fitting, calibration or threshold selection."""
    from ..ml.detectors.patchcore import PatchCore

    p = job.payload
    ds = db.get(Dataset, p["dataset_id"])
    images = list(db.scalars(select(DatasetImage).where(DatasetImage.dataset_id == ds.id, DatasetImage.label != "unlabeled")))
    if any(im.split == "unassigned" for im in images):
        raise ValueError("Dataset has images without a split. Run 'Assign splits' first.")
    st = get_storage()

    def load(sel):
        return [decode_image(st.get(im.image_key)) for im in sel]

    by = lambda split, label: [im for im in images if im.split == split and im.label == label]  # noqa: E731
    train_good = by("train", "good")
    if len(train_good) < 8:
        raise ValueError(f"Need at least 8 defect-free training images (found {len(train_good)}).")
    name = p["name"]
    existing = [int(v.version.split(".")[0]) for v in db.scalars(select(ModelVersion).where(ModelVersion.name == name))]
    version = f"{max(existing, default=0) + 1}.0.0"
    pc = PatchCore(name=name, version=version)
    progress(0.05)
    emb = pc.embed_many(load(train_good))
    progress(0.4)
    val_good, val_bad, test_good, test_bad = by("val", "good"), by("val", "defective"), by("test", "good"), by("test", "defective")
    notes = []
    if len(val_good) >= 3:
        pc.fit_embeddings(emb, coreset=min(4000, emb.shape[0] * emb.shape[1] * emb.shape[2]))
        ref_maps = pc.distance_maps(pc.embed_many(load(val_good)))
    else:  # no validation goods: hold out 20% of the training goods for the pixel threshold, then refit on all
        k = max(2, len(train_good) // 5)
        pc.fit_embeddings(emb[k:], coreset=4000)
        ref_maps = pc.distance_maps(emb[:k])
        pc.fit_embeddings(emb, coreset=4000)
        notes.append("No defect-free validation images: pixel threshold estimated from a 20% hold-out of the training goods.")
    pc.pixel_threshold = float(np.quantile(ref_maps, 0.9995) * 1.15)
    pc.score_scale = 2 * pc.pixel_threshold
    progress(0.6)

    def scores(sel):
        return [pc.image_score(d) for d in pc.distance_maps(pc.embed_many(load(sel)))] if sel else []

    metrics: dict = {}
    calibration = decision = None
    sv_g, sv_b = scores(val_good), scores(val_bad)
    drift_ref = np.quantile(sv_g, np.linspace(0, 1, 11)).round(4).tolist() if len(sv_g) >= 10 else None
    if len(sv_g) >= 5 and len(sv_b) >= 5:
        yv, xv = np.array([0] * len(sv_g) + [1] * len(sv_b)), np.array(sv_g + sv_b)
        platt = Platt.fit(xv, yv)
        t_low, t_high = select_review_band(platt(xv), yv)
        calibration = platt.to_dict()
        metrics["val"] = {"auroc": M.auroc(yv, xv), **M.binary_report(yv, platt(xv) >= 0.5), "triage": M.triage_report(yv, platt(xv), t_low, t_high)}
        st_g, st_b = scores(test_good), scores(test_bad)
        validated = len(st_g) >= 5 and len(st_b) >= 5
        if validated:
            yt, pt = np.array([0] * len(st_g) + [1] * len(st_b)), platt(np.array(st_g + st_b))
            metrics["test"] = {"auroc": M.auroc(yt, pt), **M.binary_report(yt, pt >= 0.5), "calibration": M.ece(yt, pt),
                               "triage": M.triage_report(yt, pt, t_low, t_high)}
        else:
            notes.append("Test split lacks >=5 good and >=5 defective images: the decision rule is calibrated but NOT validated.")
        decision = {"mode": "fusion", "features": [name], "coef": [platt.a], "intercept": platt.b, "t_low": t_low, "t_high": t_high,
                    "validated": validated, "image_level_validated": validated, "evidence": f"{name}-{version}-test" if validated else None}
    else:
        notes.append("Fewer than 5 good + 5 defective validation images: no calibration possible. The model can only localize candidates for human review.")
        decision = {"mode": "screening", "validated": False, "image_level_validated": False}
    base = get_settings().models_dir / name / version
    pc.save(base / "model.pt")
    card = {
        "name": name, "version": version, "kind": "anomaly", "material": ds.material_key,
        "architecture": "PatchCore: frozen ImageNet MobileNetV2 features, k-center coreset, 1-NN distance",
        "dataset": f"{ds.name} (managed dataset #{ds.id})", "trained_on": "train split, defect-free images only",
        "splits": {s: {"good": len(by(s, "good")), "defective": len(by(s, "defective"))} for s in ("train", "val", "test")},
        "calibration": calibration, "pixel_threshold": pc.pixel_threshold, "metrics": metrics, "limitations": notes + [
            "Valid only for the product, camera and lighting represented in the training images."],
        "proposed_decision": decision, "drift_reference": drift_ref, "created_at": utcnow().isoformat(),
    }
    (base / "card.json").write_text(json.dumps(card, indent=2))
    mv = ModelVersion(name=name, version=version, kind="anomaly", material_key=ds.material_key, status="candidate", card=card, created_by=job.created_by)
    db.add(mv)
    db.commit()
    get_registry().invalidate()
    return {"model_version_id": mv.id, "name": name, "version": version, "metrics": metrics, "notes": notes}
