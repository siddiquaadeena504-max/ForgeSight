from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..ml.knowledge import defect_label
from ..models import Dataset, Inspection, InspectionProfile, Material, ModelVersion, User
from ..security import audit, current_user, require_role

router = APIRouter(tags=["materials & profiles"])


def profile_out(p: InspectionProfile) -> dict:
    d = p.config.get("decision", {})
    return {"key": p.key, "material_key": p.material_key, "name": p.name, "product_category": p.product_category, "builtin": p.builtin,
            "is_active": p.is_active, "requires_reference": bool(p.config.get("requires_reference")), "mm_per_pixel": p.config.get("mm_per_pixel"),
            "detectors": p.config.get("detectors", []), "decision": d, "severity": p.config.get("severity"),
            "validated": bool(d.get("validated")), "image_level_validated": bool(d.get("image_level_validated")), "updated_at": p.updated_at.isoformat()}


@router.get("/materials")
def list_materials(_: User = Depends(current_user), db: Session = Depends(get_db)):
    profiles = list(db.scalars(select(InspectionProfile).where(InspectionProfile.is_active)))
    counts = dict(db.execute(select(Inspection.material_key, func.count()).group_by(Inspection.material_key)).all())
    ds = dict(db.execute(select(Dataset.material_key, func.count()).group_by(Dataset.material_key)).all())
    models = dict(db.execute(select(ModelVersion.material_key, func.count()).where(ModelVersion.status == "production").group_by(ModelVersion.material_key)).all())
    out = []
    for m in db.scalars(select(Material).order_by(Material.id)):
        ps = [profile_out(p) for p in profiles if p.material_key == m.key]
        out.append({"key": m.key, "name": m.name, "family": m.family, "description": m.description, "imaging_notes": m.imaging_notes, "is_custom": m.is_custom,
                    "common_defects": [{"type": t, "label": defect_label(t)} for t in m.common_defects], "profiles": ps,
                    "coverage": "validated" if any(p["validated"] for p in ps) else "screening_only",
                    "inspections": counts.get(m.key, 0), "datasets": ds.get(m.key, 0), "production_models": models.get(m.key, 0)})
    return out


class MaterialIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    family: str = Field(default="generic", max_length=64)
    description: str = Field(default="", max_length=2000)
    imaging_notes: str = Field(default="", max_length=2000)
    common_defects: list[str] = []


@router.post("/materials", status_code=201)
def create_material(body: MaterialIn, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    key = re.sub(r"[^a-z0-9]+", "_", body.name.lower()).strip("_")[:60]
    if not key or db.scalar(select(Material).where(Material.key == key)):
        raise HTTPException(409, "A material with this name already exists")
    m = Material(key=key, is_custom=True, **body.model_dump())
    db.add(m)
    audit(db, user, "material.created", "material", key, request=request)
    db.commit()
    return {"key": key}


@router.get("/profiles")
def list_profiles(material: str | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(InspectionProfile).where(InspectionProfile.is_active).order_by(InspectionProfile.id)
    if material:
        q = q.where(InspectionProfile.material_key == material)
    return [profile_out(p) for p in db.scalars(q)]


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    product_category: str | None = Field(default=None, max_length=255)
    mm_per_pixel: float | None = Field(default=None, gt=0, lt=100)
    clear_calibration: bool = False
    t_low: float | None = Field(default=None, ge=0, le=1)
    t_high: float | None = Field(default=None, ge=0, le=1)
    region_confident: float | None = Field(default=None, ge=0, le=1)
    severity: dict | None = None
    is_active: bool | None = None


@router.patch("/profiles/{key}")
def update_profile(key: str, body: ProfilePatch, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    p = db.scalar(select(InspectionProfile).where(InspectionProfile.key == key))
    if p is None:
        raise HTTPException(404, "Profile not found")
    cfg = {**p.config}
    dec = {**cfg.get("decision", {})}
    changes = body.model_dump(exclude_none=True, exclude={"clear_calibration"})
    if body.name is not None:
        p.name = body.name
    if body.product_category is not None:
        p.product_category = body.product_category
    if body.is_active is not None:
        p.is_active = body.is_active
    if body.mm_per_pixel is not None:
        cfg["mm_per_pixel"] = body.mm_per_pixel
    if body.clear_calibration:
        cfg["mm_per_pixel"] = None
    if body.severity is not None:
        cfg["severity"] = {k: v for k, v in body.severity.items() if k in ("area_major", "area_critical", "extent_major", "extent_critical", "mm_major", "mm_critical", "critical_types")}
    thresholds_changed = False
    for k in ("t_low", "t_high"):
        v = getattr(body, k)
        if v is not None:
            if dec.get("mode") != "fusion":
                raise HTTPException(422, "This profile has no probability thresholds")
            thresholds_changed |= abs(dec.get(k, -1) - v) > 1e-9
            dec[k] = v
    if dec.get("mode") == "fusion" and dec["t_low"] > dec["t_high"]:
        raise HTTPException(422, "t_low must not exceed t_high")
    if body.region_confident is not None:
        thresholds_changed |= dec.get("region_confident") != body.region_confident
        dec["region_confident"] = body.region_confident
    if thresholds_changed and dec.get("validated"):
        # Hand-edited thresholds were not the ones evaluated: the profile loses its validated status until re-evaluated.
        dec.update({"validated": False, "image_level_validated": False, "evidence": None,
                    "note": f"Thresholds edited by {user.email}; validation evidence no longer applies."})
    cfg["decision"] = dec
    cfg["edited"] = True
    p.config = cfg
    audit(db, user, "profile.updated", "profile", key, changes, request)
    db.commit()
    return profile_out(p)
