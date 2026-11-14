from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..ml.drift import psi_from_quantiles, psi_status, quantiles
from ..models import Dataset, EvaluationRun, Inspection, InspectionProfile, ModelVersion, User
from ..security import audit, current_user, require_role
from ..services import handlers  # noqa: F401
from ..services.engine import get_registry
from ..services.jobs import job_out, submit

router = APIRouter(tags=["models"])


def headline(e: EvaluationRun) -> list[dict]:
    """Pick the few numbers that summarise an evaluation, straight from its stored metrics."""
    m = e.metrics
    out = []

    def add(label, value, ci=None):
        if value is not None:
            out.append({"label": label, "value": value, "ci95": ci})

    if "test" in m and isinstance(m["test"], dict) and "auroc" in m["test"]:
        t = m["test"]
        add("AUROC", t.get("auroc")); add("F1", t.get("f1")); add("Precision", t.get("precision")); add("Recall", t.get("recall"), t.get("recall_ci95"))
        add("False-positive rate", t.get("false_positive_rate"), t.get("fpr_ci95")); add("False-negative rate", t.get("false_negative_rate"), t.get("fnr_ci95"))
        if "accuracy" in t:
            add("Accuracy", t.get("accuracy"), t.get("accuracy_ci95"))
    if "localization" in m:
        add("Localization F1", m["localization"]["f1"]); add("Localization recall", m["localization"]["recall"], m["localization"].get("recall_ci95"))
        add("Class-aware F1", m["class_aware"]["f1"]); add("Class-aware precision", m["class_aware"]["precision"])
        add("False-negative rate (defects)", m["localization"]["false_negative_rate"])
    if "test_pixel_strict" in m:
        add("Pixel F1 (strict)", m["test_pixel_strict"]["pixel_f1"]); add("IoU", m["test_pixel_strict"]["iou"])
        add("Pixel F1 (2 px tolerance)", m["test_pixel_tolerant"]["pixel_f1"])
    if "test" in m and isinstance(m["test"], dict) and "macro_f1" in m["test"]:
        add("Accuracy", m["test"]["accuracy"], m["test"].get("accuracy_ci95")); add("Macro F1", m["test"]["macro_f1"])
    return out


def eval_out(e: EvaluationRun) -> dict:
    return {"id": e.eval_key, "model": e.model_name, "version": e.model_version, "material_key": e.material_key, "dataset": e.dataset, "split": e.split,
            "task": e.task, "n": e.n, "metrics": e.metrics, "notes": e.notes, "hardware": e.hardware, "created_at": e.created_at.isoformat(), "headline": headline(e)}


def model_out(m: ModelVersion) -> dict:
    return {"id": m.id, "name": m.name, "version": m.version, "kind": m.kind, "material_key": m.material_key, "status": m.status, "card": m.card,
            "created_by": m.created_by, "created_at": m.created_at.isoformat()}


@router.get("/models")
def list_models(_: User = Depends(current_user), db: Session = Depends(get_db)):
    profiles = list(db.scalars(select(InspectionProfile).where(InspectionProfile.is_active)))
    out = []
    for m in db.scalars(select(ModelVersion).order_by(ModelVersion.name, ModelVersion.id.desc())):
        o = model_out(m)
        o["used_by_profiles"] = [p.key for p in profiles if any(d.get("model") == m.name and d.get("version") == m.version for d in p.config.get("detectors", []))]
        out.append(o)
    return out


@router.get("/evaluations")
def list_evaluations(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [eval_out(e) for e in db.scalars(select(EvaluationRun).order_by(EvaluationRun.material_key, EvaluationRun.model_name))]


class TrainIn(BaseModel):
    dataset_id: int
    name: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9_]+$")


@router.post("/models/train", status_code=202)
def train_model(body: TrainIn, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    if db.get(Dataset, body.dataset_id) is None:
        raise HTTPException(404, "Dataset not found")
    job = submit(db, "fit_patchcore", {"dataset_id": body.dataset_id, "name": body.name}, user.email)
    audit(db, user, "model.training_started", "job", job.id, body.model_dump(), request)
    db.commit()
    return job_out(job)


class PromoteIn(BaseModel):
    profile_name: str | None = Field(default=None, max_length=255)


@router.post("/models/{model_id}/promote")
def promote_model(model_id: int, body: PromoteIn, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    """Candidate -> production. For in-app anomaly models this also creates/updates the inspection profile that uses the model."""
    m = db.get(ModelVersion, model_id)
    if m is None:
        raise HTTPException(404, "Model version not found")
    for other in db.scalars(select(ModelVersion).where(ModelVersion.name == m.name, ModelVersion.status == "production", ModelVersion.id != m.id)):
        other.status = "archived"
    m.status = "production"
    profile_key = None
    dec = m.card.get("proposed_decision")
    if m.kind == "anomaly" and dec:
        profile_key = re.sub(r"[^a-z0-9]+", "_", m.name)[:60]
        spec = {"type": "patchcore", "model": m.name, "version": m.version}
        if m.card.get("calibration"):
            spec["calibration"] = m.card["calibration"]
        cfg = {"detectors": [spec], "decision": dec, "requires_reference": False, "mm_per_pixel": None}
        if m.card.get("drift_reference"):
            cfg["drift_reference"] = {m.name: m.card["drift_reference"]}
        p = db.scalar(select(InspectionProfile).where(InspectionProfile.key == profile_key))
        if p is None:
            db.add(InspectionProfile(key=profile_key, material_key=m.material_key, name=body.profile_name or f"{m.name} (anomaly model)", config=cfg))
        else:
            cfg["mm_per_pixel"] = p.config.get("mm_per_pixel")
            p.config, p.is_active = cfg, True
            if body.profile_name:
                p.name = body.profile_name
    get_registry().invalidate()
    audit(db, user, "model.promoted", "model_version", m.id, {"name": m.name, "version": m.version, "profile": profile_key}, request)
    db.commit()
    return {**model_out(m), "profile_key": profile_key}


@router.post("/models/{model_id}/archive")
def archive_model(model_id: int, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    m = db.get(ModelVersion, model_id)
    if m is None:
        raise HTTPException(404, "Model version not found")
    used = [p.key for p in db.scalars(select(InspectionProfile).where(InspectionProfile.is_active))
            if any(d.get("model") == m.name and d.get("version") == m.version for d in p.config.get("detectors", []))]
    if used:
        raise HTTPException(409, f"Model is used by active profile(s): {', '.join(used)}. Deactivate or repoint them first.")
    m.status = "archived"
    audit(db, user, "model.archived", "model_version", m.id, request=request)
    db.commit()
    return model_out(m)


@router.get("/monitoring/production")
def production_monitoring(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """What happened to AI decisions in production: human agreement, and - where ground truth exists - measured errors."""
    out = []
    keys = [k for (k,) in db.execute(select(Inspection.profile_key).group_by(Inspection.profile_key))]
    for key in keys:
        cond = Inspection.profile_key == key if key else Inspection.profile_key.is_(None)
        rows = db.execute(select(Inspection.outcome, Inspection.final_outcome, Inspection.review_status, Inspection.ground_truth).where(cond)).all()
        n = len(rows)
        auto = [r for r in rows if r.outcome in ("pass", "defective")]
        audited = [r for r in auto if r.review_status in ("confirmed", "corrected")]
        overturned = sum(1 for r in audited if r.final_outcome != r.outcome)
        gt = [r for r in rows if r.ground_truth in ("good", "defective")]
        g = None
        if gt:
            esc = sum(1 for r in gt if r.outcome == "pass" and r.ground_truth == "defective")
            fr = sum(1 for r in gt if r.outcome == "defective" and r.ground_truth == "good")
            nd, ng = sum(1 for r in gt if r.ground_truth == "defective"), sum(1 for r in gt if r.ground_truth == "good")
            g = {"n": len(gt), "defective": nd, "good": ng, "escaped_defects": esc, "false_rejects": fr,
                 "sent_to_review": sum(1 for r in gt if r.outcome == "review"),
                 "correct_auto_decisions": sum(1 for r in gt if (r.outcome == "pass" and r.ground_truth == "good") or (r.outcome == "defective" and r.ground_truth == "defective"))}
        out.append({"profile_key": key or "generic_screening", "inspections": n, "auto_decided": len(auto),
                    "review_rate": round(1 - len(auto) / n, 4) if n else None, "auto_decisions_audited_by_human": len(audited),
                    "auto_decisions_overturned": overturned, "labelled_replay": g})
    return out


@router.get("/monitoring/drift")
def drift(window: int = 200, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """PSI of recent detector scores / image brightness against the validation-time reference of each profile.
    Profiles without a stored reference use their own first `window` inspections as the baseline."""
    out = []
    for p in db.scalars(select(InspectionProfile).where(InspectionProfile.is_active)):
        total = db.scalar(select(func.count()).where(Inspection.profile_key == p.key))
        if not total:
            out.append({"profile_key": p.key, "inspections": 0, "signals": []})
            continue
        recent = [s for (s,) in db.execute(select(Inspection.summary).where(Inspection.profile_key == p.key).order_by(Inspection.created_at.desc()).limit(window))]
        first = [s for (s,) in db.execute(select(Inspection.summary).where(Inspection.profile_key == p.key).order_by(Inspection.created_at.asc()).limit(window))]

        def series(summaries, name):
            vals = []
            for s in summaries:
                if name == "brightness":
                    v = next((c["value"] for c in s.get("quality", {}).get("checks", []) if c["name"] == "exposure"), None)
                else:
                    v = next((d["image_score"] for d in s.get("detectors", []) if d["name"] == name), None)
                if v is not None:
                    vals.append(v)
            return vals

        ref = p.config.get("drift_reference") or {}
        names = ["brightness"] + [d.get("model") or d["type"] for d in p.config.get("detectors", [])]
        signals = []
        for name in names:
            live = series(recent, name)
            if name in ref:
                base, basis = ref[name], "validation split (defect-free)" if name != "brightness" else "validation split"
            elif total >= 2 * window and len(series(first, name)) >= 20:
                base, basis = quantiles(series(first, name)), f"first {window} production inspections"
            else:
                signals.append({"signal": name, "psi": None, "status": "no_reference", "n_recent": len(live), "reference": None})
                continue
            psi = psi_from_quantiles(base, live)
            signals.append({"signal": name, "psi": psi, "status": psi_status(psi), "n_recent": len(live), "reference": basis,
                            "recent_mean": round(sum(live) / len(live), 4) if live else None, "reference_median": base[5]})
        out.append({"profile_key": p.key, "inspections": total, "signals": signals})
    return out
