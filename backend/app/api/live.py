from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..ml.imageops import decode_image
from ..models import User
from ..security import require_role
from ..services import live_sessions
from ..services.inspection import run_inspection
from .inspections import read_upload

router = APIRouter(tags=["live"])


@router.post("/live/reference", status_code=201)
async def learn_reference(files: list[UploadFile] = File(...), _: User = Depends(require_role("inspector"))):
    """Learn the normal appearance of a material from 6-60 defect-free frames (for materials without a trained model).
    Returns a session id to pass to /live/frame. The session lives in memory for a few hours."""
    if not 6 <= len(files) <= 60:
        raise HTTPException(422, "Send between 6 and 60 reference frames")
    frames = []
    for f in files:
        try:
            frames.append(decode_image(await read_upload(f, get_settings().max_upload_mb)))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    if len({fr.shape[:2] for fr in frames}) != 1:
        raise HTTPException(422, "All reference frames must have the same resolution")
    _, info = live_sessions.create(frames)
    return info


@router.post("/live/frame")
async def live_frame(file: UploadFile = File(...), material_key: str | None = Form(None), profile_key: str | None = Form(None),
                     batch_id: str | None = Form(None, max_length=120), save: str = Form("flagged", pattern="^(never|flagged|always)$"),
                     session_id: str | None = Form(None, max_length=64), sensitivity: str = Form("normal", pattern="^(low|normal|high)$"),
                     user: User = Depends(require_role("inspector")), db: Session = Depends(get_db)):
    """Inspect one camera frame. By default only frames that are not a clean PASS are stored (and enter the review queue)."""
    data = await read_upload(file, get_settings().max_upload_mb)
    override = None
    if session_id:
        if live_sessions.get(session_id) is None:
            raise HTTPException(410, "The reference-learning session has expired; learn the reference again")
        override = live_sessions.profile_for(session_id, sensitivity)
    keep = {"never": False, "always": True, 
            # flagged = anything a person should look at; a screening frame with no deviation at all is not stored
            "flagged": lambda r: r.summary["decision"]["outcome"] == "defective" or (
                r.summary["decision"]["outcome"] == "review" and (bool(r.findings) or r.summary["decision"]["mode"] != "screening"))}[save]
    insp, res = run_inspection(db, image_bytes=data, filename="live-frame.jpg", user_email=user.email, material_key=material_key or None,
                               profile_key=profile_key or None, batch_id=batch_id, source="live", persist=keep, profile_override=override)
    out = {"decision": res.summary["decision"], "quality": {"status": res.summary["quality"]["status"]}, "processing_ms": res.summary["processing_ms"],
           "image": res.summary["image"], "saved_inspection_id": insp.id if insp else None,
           "findings": [{k: f[k] for k in ("defect_type", "label", "type_source", "confidence", "bbox", "polygon", "severity", "location")} for f in res.findings]}
    return out
