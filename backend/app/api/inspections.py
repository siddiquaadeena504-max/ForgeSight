from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..db import get_db
from ..ml.imageops import decode_image
from ..ml.knowledge import TAXONOMY, defect_category, defect_label
from ..ml.quality import assess_quality
from ..models import Defect, Inspection, Job, User, new_id, utcnow
from ..security import audit, current_user, require_role
from ..services import handlers  # noqa: F401  (registers job handlers)
from ..services.inspection import identify, inspection_out, run_inspection
from ..services.jobs import job_out, submit
from ..storage import get_storage, verify_signature

router = APIRouter(tags=["inspections"])
IMAGE_TYPES = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp"}


async def read_upload(file: UploadFile, max_mb: int, kinds: set[str] | None = IMAGE_TYPES) -> bytes:
    if kinds is not None and file.content_type not in kinds:
        raise HTTPException(415, f"Unsupported file type '{file.content_type}'")
    data = await file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds the {max_mb} MB limit")
    if not data:
        raise HTTPException(422, "Empty file")
    return data


@router.post("/inspections/identify")
async def identify_image(file: UploadFile = File(...), _: User = Depends(require_role("inspector"))):
    """Step 1-3 of the workflow: suggest material/profile and analyse image quality before inspecting."""
    data = await read_upload(file, get_settings().max_upload_mb)
    try:
        img = decode_image(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"suggestion": identify(img), "quality": assess_quality(img)}


@router.post("/inspections", status_code=201)
async def create_inspection(
    request: Request, file: UploadFile = File(...), reference: UploadFile | None = File(None),
    material_key: str | None = Form(None, max_length=64), profile_key: str | None = Form(None, max_length=64),
    product_id: str | None = Form(None, max_length=120), batch_id: str | None = Form(None, max_length=120),
    mm_per_pixel: float | None = Form(None, gt=0, lt=100), material_overridden: bool = Form(False), material_from_suggestion: bool = Form(False),
    user: User = Depends(require_role("inspector")), db: Session = Depends(get_db),
):
    s = get_settings()
    data = await read_upload(file, s.max_upload_mb)
    ref = await read_upload(reference, s.max_upload_mb) if reference is not None else None
    insp, _ = run_inspection(db, image_bytes=data, filename=file.filename, user_email=user.email, material_key=material_key or None,
                             profile_key=profile_key or None, product_id=product_id, batch_id=batch_id, reference_bytes=ref, mm_per_pixel=mm_per_pixel)
    if material_overridden:
        insp.material_source = "override"
    elif material_from_suggestion:  # operator accepted the pre-selected AI suggestion unchanged
        insp.material_source = "suggested"
    audit(db, user, "inspection.created", "inspection", insp.id, {"outcome": insp.outcome, "material": insp.material_key, "profile": insp.profile_key}, request)
    db.commit()
    return inspection_out(insp, detail=True)


@router.post("/inspections/video", status_code=202)
async def create_video_inspection(
    request: Request, file: UploadFile = File(...), material_key: str | None = Form(None), profile_key: str | None = Form(None),
    batch_id: str | None = Form(None, max_length=120), product_id: str | None = Form(None, max_length=120),
    every_seconds: float = Form(1.0, gt=0.03, le=60), max_frames: int = Form(60, ge=1, le=600),
    user: User = Depends(require_role("inspector")), db: Session = Depends(get_db),
):
    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(415, "Expected a video file")
    if not material_key and not profile_key:
        raise HTTPException(422, "Select a material or an inspection profile for video inspection")
    data = await read_upload(file, get_settings().max_video_mb, kinds=None)
    key = f"uploads/video/{new_id()}"
    get_storage().put(key, data, file.content_type or "video/mp4")
    job = submit(db, "video_inspection", {"storage_key": key, "filename": file.filename, "material_key": material_key or None, "profile_key": profile_key or None,
                                          "batch_id": batch_id, "product_id": product_id, "every_seconds": every_seconds, "max_frames": max_frames}, user.email)
    audit(db, user, "inspection.video_submitted", "job", job.id, {"filename": file.filename}, request)
    db.commit()
    return job_out(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job_out(job)


@router.get("/jobs")
def list_jobs(kind: str | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Job).order_by(Job.created_at.desc()).limit(50)
    if kind:
        q = q.where(Job.kind == kind)
    return [job_out(j) for j in db.scalars(q)]


def apply_filters(q, *, outcome=None, material=None, batch=None, source=None, review_status=None, search=None, date_from=None, date_to=None,
                  job_id=None, defect_type=None, profile=None):
    eff = func.coalesce(Inspection.final_outcome, Inspection.outcome)
    if outcome:
        q = q.where(eff == outcome)
    if material:
        q = q.where(Inspection.material_key == material)
    if profile:
        q = q.where(Inspection.profile_key == profile)
    if batch:
        q = q.where(Inspection.batch_id == batch)
    if source:
        q = q.where(Inspection.source == source)
    if review_status:
        q = q.where(Inspection.review_status == review_status)
    if job_id:
        q = q.where(Inspection.job_id == job_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(Inspection.product_id.ilike(like), Inspection.batch_id.ilike(like), Inspection.filename.ilike(like), Inspection.id.ilike(like)))
    if date_from:
        q = q.where(Inspection.created_at >= date_from)
    if date_to:
        q = q.where(Inspection.created_at < date_to + timedelta(days=1) if date_to.hour == 0 and date_to.minute == 0 else Inspection.created_at <= date_to)
    if defect_type:
        q = q.where(Inspection.id.in_(select(Defect.inspection_id).where(Defect.defect_type == defect_type)))
    return q


@router.get("/inspections")
def list_inspections(
    outcome: str | None = Query(None, pattern="^(pass|review|defective)$"), material: str | None = None, batch: str | None = None,
    source: str | None = None, review_status: str | None = None, search: str | None = Query(None, max_length=120),
    date_from: datetime | None = None, date_to: datetime | None = None, job_id: str | None = None, defect_type: str | None = None,
    profile: str | None = None, sort: str = Query("newest", pattern="^(newest|oldest|uncertain)$"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    _: User = Depends(current_user), db: Session = Depends(get_db),
):
    kw = dict(outcome=outcome, material=material, batch=batch, source=source, review_status=review_status, search=search, date_from=date_from,
              date_to=date_to, job_id=job_id, defect_type=defect_type, profile=profile)
    total = db.scalar(apply_filters(select(func.count(Inspection.id)), **kw))
    q = apply_filters(select(Inspection), **kw)
    if sort == "uncertain":  # active learning: closest to the decision boundary first
        q = q.order_by(func.abs(func.coalesce(Inspection.p_defect, 0.5) - 0.5), Inspection.created_at.desc())
    else:
        q = q.order_by(Inspection.created_at.desc() if sort == "newest" else Inspection.created_at.asc())
    return {"total": total, "items": [inspection_out(i) for i in db.scalars(q.limit(limit).offset(offset))]}


@router.get("/inspections/{inspection_id}")
def get_inspection(inspection_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)):
    i = db.scalar(select(Inspection).options(selectinload(Inspection.defects)).where(Inspection.id == inspection_id))
    if i is None:
        raise HTTPException(404, "Inspection not found")
    return inspection_out(i, detail=True)


class DefectReview(BaseModel):
    id: int
    qc_status: str = Field(pattern="^(confirmed|rejected|corrected)$")
    human_type: str | None = Field(default=None, max_length=64)


class NewDefect(BaseModel):
    defect_type: str = Field(max_length=64)
    bbox: list[int] = Field(min_length=4, max_length=4)


class ReviewIn(BaseModel):
    final_outcome: str = Field(pattern="^(pass|defective)$")
    notes: str | None = Field(default=None, max_length=4000)
    defects: list[DefectReview] = []
    missed_defects: list[NewDefect] = []


@router.post("/inspections/{inspection_id}/review")
def review_inspection(inspection_id: str, body: ReviewIn, request: Request, user: User = Depends(require_role("inspector")), db: Session = Depends(get_db)):
    """Human disposition. The AI outcome is preserved; `final_outcome` records the inspector's decision."""
    i = db.scalar(select(Inspection).options(selectinload(Inspection.defects)).where(Inspection.id == inspection_id))
    if i is None:
        raise HTTPException(404, "Inspection not found")
    by_id = {d.id: d for d in i.defects}
    changed = False
    for r in body.defects:
        d = by_id.get(r.id)
        if d is None:
            raise HTTPException(422, f"Defect {r.id} does not belong to this inspection")
        if r.qc_status == "corrected" and not r.human_type:
            raise HTTPException(422, "A corrected defect needs the inspector's defect type")
        d.qc_status, d.reviewed_by = r.qc_status, user.email
        d.human_type = r.human_type if r.qc_status == "corrected" else None
        changed |= r.qc_status != "confirmed"
    for m in body.missed_defects:
        x, y, w, h = m.bbox
        idx = max((d.idx for d in i.defects), default=0) + 1
        data = {"defect_type": m.defect_type, "label": defect_label(m.defect_type), "category": defect_category(m.defect_type), "type_source": "human",
                "type_confidence": None, "confidence": 1.0, "confidence_basis": "human", "bbox": m.bbox, "polygon": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                "centroid": [x + w / 2, y + h / 2], "location": "marked by inspector", "area_ratio": 0, "sources": ["human"], "agreement": 1,
                "dimensions": {"length_px": float(max(w, h)), "width_px": float(min(w, h)), "area_px": w * h, "calibrated": False},
                "severity": {"level": "major", "score": 0.5, "rationale": "Added by inspector; severity not estimated."}, "detector_scores": {},
                "cause_hypotheses": [], "recommended_action": "Disposition per inspector."}
        i.defects.append(Defect(idx=idx, defect_type=m.defect_type, label=data["label"], category=data["category"], type_source="human", confidence=1.0,
                                severity="major", data=data, qc_status="confirmed", reviewed_by=user.email))
        changed = True
    ai_auto = i.outcome if i.outcome != "review" else None
    i.final_outcome = body.final_outcome
    i.review_status = "corrected" if changed or (ai_auto and ai_auto != body.final_outcome) else "confirmed"
    i.reviewed_by, i.reviewed_at, i.review_notes = user.email, utcnow(), body.notes
    i.defect_count = sum(1 for d in i.defects if d.qc_status != "rejected")
    audit(db, user, "inspection.reviewed", "inspection", i.id, {"ai_outcome": i.outcome, "final_outcome": i.final_outcome, "review_status": i.review_status}, request)
    db.commit()
    return inspection_out(i, detail=True)


@router.delete("/inspections/{inspection_id}", status_code=204)
def delete_inspection(inspection_id: str, request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    i = db.get(Inspection, inspection_id)
    if i is None:
        raise HTTPException(404, "Inspection not found")
    st = get_storage()
    for k in (i.image_key, i.annotated_key, i.heatmap_key, i.thumb_key, i.reference_key):
        if k:
            st.delete(k)
    db.delete(i)
    audit(db, user, "inspection.deleted", "inspection", inspection_id, request=request)
    db.commit()
    return Response(status_code=204)


@router.get("/files/{key:path}", include_in_schema=False)
def get_file(key: str, exp: int, sig: str):
    """Signed, expiring object access (works for <img> tags without exposing the bearer token)."""
    if not verify_signature(key, exp, sig):
        raise HTTPException(403, "Invalid or expired link")
    try:
        data = get_storage().get(key)
    except Exception:
        raise HTTPException(404, "File not found")
    ext = key.rsplit(".", 1)[-1].lower()
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "application/octet-stream")
    return Response(data, media_type=media, headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"})


@router.get("/taxonomy")
def taxonomy(_: User = Depends(current_user)):
    return [{"type": k, "label": v[0], "category": v[1]} for k, v in TAXONOMY.items()]
