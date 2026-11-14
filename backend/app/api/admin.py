from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, Setting, User
from ..security import audit, current_user, require_role
from ..services.engine import get_material_identifier, system_info
from ..services.inspection import get_policy

router = APIRouter(tags=["settings"])


class PolicyIn(BaseModel):
    allow_unvalidated_pass: bool
    review_on_quality_warn: bool
    disagreement_delta: float = Field(ge=0.1, le=1.0)


@router.get("/settings/policy")
def read_policy(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_policy(db)


@router.put("/settings/policy")
def write_policy(body: PolicyIn, request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    row = db.get(Setting, "policy")
    before = dict(row.value) if row else {}
    if row is None:
        db.add(Setting(key="policy", value=body.model_dump()))
    else:
        row.value = body.model_dump()
    audit(db, user, "settings.policy_updated", "setting", "policy", {"before": before, "after": body.model_dump()}, request)
    db.commit()
    return get_policy(db)


@router.get("/settings/system")
def system(_: User = Depends(current_user)):
    s = get_settings()
    return {**system_info(), "environment": s.env, "storage_backend": s.storage_backend, "database": s.database_url.split("://")[0],
            "material_identifier_installed": get_material_identifier() is not None, "max_upload_mb": s.max_upload_mb, "max_video_mb": s.max_video_mb,
            "default_secret_in_use": s.secret_key.startswith("dev-only")}


@router.get("/audit")
def audit_log(action: str | None = None, user_email: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              _: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    if user_email:
        q = q.where(AuditLog.user_email == user_email)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    return {"total": total, "items": [{"id": a.id, "ts": a.ts.isoformat(), "user_email": a.user_email, "action": a.action, "entity": a.entity,
                                       "entity_id": a.entity_id, "detail": a.detail, "ip": a.ip} for a in rows]}
