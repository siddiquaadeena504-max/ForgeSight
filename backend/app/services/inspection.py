from __future__ import annotations

import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ml.imageops import decode_image
from ..ml.pipeline import DEFAULT_POLICY, GENERIC_PROFILE
from ..ml.render import annotate, encode_jpg, heatmap_rgba, thumbnail
from ..models import Defect, Inspection, InspectionProfile, Material, Setting, new_id
from ..storage import get_storage, signed_url
from .engine import get_engine, get_material_identifier

SEV_RANK = {"minor": 1, "major": 2, "critical": 3}


def get_policy(db: Session) -> dict:
    row = db.get(Setting, "policy")
    return {**DEFAULT_POLICY, **(row.value if row else {})}


def profile_config(p: InspectionProfile) -> dict:
    return {**p.config, "key": p.key, "name": p.name}


def identify(img) -> dict:
    """Suggest a specialised profile/material for an image, or say honestly that we do not know."""
    ident = get_material_identifier()
    if ident is None:
        return {"known": False, "material": None, "profile_key": None, "method": "no identifier model installed", "candidates": []}
    s = ident.suggest(img)
    s["profile_key"] = s.pop("material")  # prototypes are keyed by inspection profile
    return s


def resolve_material_and_profile(db: Session, img, material_key: str | None, profile_key: str | None):
    suggestion = None
    source = "user"
    profile = None
    if profile_key:
        profile = db.scalar(select(InspectionProfile).where(InspectionProfile.key == profile_key, InspectionProfile.is_active))
        if profile is None:
            raise HTTPException(404, f"Inspection profile '{profile_key}' not found")
        if material_key and material_key != profile.material_key:
            raise HTTPException(422, f"Profile '{profile_key}' belongs to material '{profile.material_key}', not '{material_key}'")
        material_key = profile.material_key
    elif not material_key:
        suggestion = identify(img)
        if suggestion["known"]:
            profile = db.scalar(select(InspectionProfile).where(InspectionProfile.key == suggestion["profile_key"], InspectionProfile.is_active))
        if profile is None:
            raise HTTPException(422, {"code": "material_required", "message": "The material could not be identified with confidence. "
                                      "Select the material (and optionally an inspection profile) manually.", "suggestion": suggestion})
        material_key, source = profile.material_key, "suggested"
    if db.scalar(select(Material).where(Material.key == material_key)) is None:
        raise HTTPException(404, f"Unknown material '{material_key}'")
    return material_key, profile, source, suggestion


def run_inspection(db: Session, *, image_bytes: bytes, filename: str | None, user_email: str | None, material_key: str | None = None,
                   profile_key: str | None = None, product_id: str | None = None, batch_id: str | None = None,
                   reference_bytes: bytes | None = None, mm_per_pixel: float | None = None, source: str = "upload",
                   ground_truth: str | None = None, job_id: str | None = None, frame_index: int | None = None,
                   created_at=None, persist=True, profile_override: dict | None = None):
    """`persist` may be a bool or a predicate on the engine result (used by live mode to store only flagged frames)."""
    try:
        img = decode_image(image_bytes)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    material_key, profile, mat_source, suggestion = resolve_material_and_profile(db, img, material_key, profile_key)
    reference = None
    if reference_bytes:
        try:
            reference = decode_image(reference_bytes)
        except ValueError:
            raise HTTPException(422, "Reference image is not a readable image")
    cfg = profile_override or (profile_config(profile) if profile else {**GENERIC_PROFILE})
    result = get_engine().inspect(img, material_key, cfg, reference_bgr=reference, mm_per_pixel=mm_per_pixel, policy=get_policy(db))
    if not (persist(result) if callable(persist) else persist):
        return None, result

    iid = new_id()
    st = get_storage()
    prefix = f"inspections/{iid[:2]}/{iid}"
    ext = "png" if image_bytes[:4] == b"\x89PNG" else "jpg"
    keys = {"image_key": f"{prefix}/original.{ext}", "annotated_key": f"{prefix}/annotated.jpg", "thumb_key": f"{prefix}/thumb.jpg"}
    st.put(keys["image_key"], image_bytes, f"image/{'png' if ext == 'png' else 'jpeg'}")
    st.put(keys["annotated_key"], encode_jpg(annotate(img, result.findings)), "image/jpeg")
    st.put(keys["thumb_key"], thumbnail(img), "image/jpeg")
    if result.heatmap is not None:
        keys["heatmap_key"] = f"{prefix}/heatmap.png"
        st.put(keys["heatmap_key"], heatmap_rgba(result.heatmap), "image/png")
    if reference_bytes:
        keys["reference_key"] = f"{prefix}/reference.jpg"
        st.put(keys["reference_key"], reference_bytes, "image/jpeg")

    dec = result.summary["decision"]
    sevs = [f["severity"]["level"] for f in result.findings]
    insp = Inspection(
        id=iid, created_by=user_email, product_id=product_id or None, batch_id=batch_id or None, filename=filename, material_key=material_key,
        material_source=mat_source, material_suggestion=suggestion, profile_key=profile.key if profile else None, source=source,
        job_id=job_id, frame_index=frame_index, status="done", outcome=dec["outcome"], final_outcome=None if dec["outcome"] == "review" else dec["outcome"],
        p_defect=dec["p_defect"], quality_status=result.summary["quality"]["status"], defect_count=len(result.findings),
        max_severity=max(sevs, key=SEV_RANK.get) if sevs else None, processing_ms=result.summary["processing_ms"], summary=result.summary,
        sha256=hashlib.sha256(image_bytes).hexdigest(), ground_truth=ground_truth,
        review_status="pending" if dec["outcome"] == "review" else None, **keys,
    )
    if created_at is not None:
        insp.created_at = created_at
    for i, f in enumerate(result.findings, 1):
        insp.defects.append(Defect(idx=i, defect_type=f["defect_type"], label=f["label"], category=f["category"], type_source=f["type_source"],
                                   confidence=f["confidence"], severity=f["severity"]["level"], data=f))
    db.add(insp)
    db.commit()
    return insp, result


def defect_out(d: Defect) -> dict:
    return {"id": d.id, "idx": d.idx, "qc_status": d.qc_status, "human_type": d.human_type, "reviewed_by": d.reviewed_by, **d.data}


def inspection_out(i: Inspection, detail: bool = False) -> dict:
    out = {
        "id": i.id, "created_at": i.created_at.isoformat(), "created_by": i.created_by, "product_id": i.product_id, "batch_id": i.batch_id,
        "filename": i.filename, "material_key": i.material_key, "material_source": i.material_source, "profile_key": i.profile_key,
        "source": i.source, "job_id": i.job_id, "frame_index": i.frame_index, "status": i.status, "outcome": i.outcome,
        "final_outcome": i.final_outcome, "p_defect": i.p_defect, "quality_status": i.quality_status, "defect_count": i.defect_count,
        "max_severity": i.max_severity, "processing_ms": i.processing_ms, "review_status": i.review_status, "reviewed_by": i.reviewed_by,
        "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None, "ground_truth": i.ground_truth, "thumb_url": signed_url(i.thumb_key),
    }
    if detail:
        out.update({
            "summary": i.summary, "material_suggestion": i.material_suggestion, "review_notes": i.review_notes,
            "image_url": signed_url(i.image_key), "annotated_url": signed_url(i.annotated_key), "heatmap_url": signed_url(i.heatmap_key),
            "reference_url": signed_url(i.reference_key), "defects": [defect_out(d) for d in i.defects],
        })
    return out
