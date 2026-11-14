from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..ml.knowledge import defect_label
from ..models import Defect, Inspection, Material, User
from ..security import current_user

router = APIRouter(tags=["analytics"])
EFF = func.coalesce(Inspection.final_outcome, Inspection.outcome)


def _counts(prefix_cols: list, group: list, where: list, db: Session):
    q = select(*prefix_cols, func.count().label("total"),
               func.sum(case((EFF == "pass", 1), else_=0)).label("passed"),
               func.sum(case((EFF == "review", 1), else_=0)).label("review"),
               func.sum(case((EFF == "defective", 1), else_=0)).label("defective")).where(*where)
    if group:
        q = q.group_by(*group)
    return db.execute(q).all()


def window(days: int | None, material: str | None, date_from: datetime | None = None, date_to: datetime | None = None) -> list:
    w = []
    if date_from:
        w.append(Inspection.created_at >= date_from)
    elif days:
        w.append(Inspection.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
    if date_to:
        w.append(Inspection.created_at < date_to + timedelta(days=1))
    if material:
        w.append(Inspection.material_key == material)
    return w


def compute(db: Session, where: list) -> dict:
    total, passed, review, defective = _counts([], [], where, db)[0]
    pend = db.scalar(select(func.count()).where(Inspection.review_status == "pending", *where))
    times = np.array([t for (t,) in db.execute(select(Inspection.processing_ms).where(Inspection.processing_ms.is_not(None), *where))], dtype=float)
    names = {m.key: m.name for m in db.scalars(select(Material))}
    live = Defect.qc_status != "rejected"

    by_type = db.execute(
        select(Defect.defect_type, func.count(), func.sum(case((Defect.severity == "critical", 1), else_=0)),
               func.sum(case((Defect.severity == "major", 1), else_=0)), func.sum(case((Defect.severity == "minor", 1), else_=0)),
               func.sum(case((Defect.type_source == "model", 1), else_=0)))
        .join(Inspection).where(live, *where).group_by(Defect.defect_type).order_by(func.count().desc())).all()
    defects_by_mat = dict(db.execute(select(Inspection.material_key, func.count()).join(Defect).where(live, *where).group_by(Inspection.material_key)).all())
    mat_type = db.execute(select(Inspection.material_key, Defect.defect_type, func.count()).join(Defect).where(live, *where)
                          .group_by(Inspection.material_key, Defect.defect_type)).all()
    by_material = [{"material_key": k, "material": names.get(k, k), "total": t, "passed": int(p or 0), "review": int(r or 0), "defective": int(d or 0),
                    "defects": defects_by_mat.get(k, 0), "defect_types": {dt: n for mk, dt, n in mat_type if mk == k}}
                   for k, t, p, r, d in _counts([Inspection.material_key], [Inspection.material_key], where, db)]
    batch_defects = dict(db.execute(select(Inspection.batch_id, func.count()).join(Defect).where(live, Inspection.batch_id.is_not(None), *where)
                                    .group_by(Inspection.batch_id)).all())
    by_batch = sorted(({"batch": b, "total": t, "passed": int(p or 0), "review": int(r or 0), "defective": int(d or 0), "defects": batch_defects.get(b, 0),
                        "first_seen": fs.isoformat() if hasattr(fs, "isoformat") else str(fs)}
                       for b, fs, t, p, r, d in _counts([Inspection.batch_id, func.min(Inspection.created_at)], [Inspection.batch_id],
                                                        [Inspection.batch_id.is_not(None), *where], db)), key=lambda r: r["first_seen"])
    day = func.date(Inspection.created_at)
    trend = [{"date": str(dt), "total": t, "passed": int(p or 0), "review": int(r or 0), "defective": int(d or 0),
              "defect_rate": round(int(d or 0) / t, 4) if t else None}
             for dt, t, p, r, d in sorted(_counts([day], [day], where, db), key=lambda r: str(r[0]))]
    by_source = dict(db.execute(select(Inspection.source, func.count()).where(*where).group_by(Inspection.source)).all())
    span = db.execute(select(func.min(Inspection.created_at), func.max(Inspection.created_at)).where(*where)).one()
    hours = max(1 / 60, (span[1] - span[0]).total_seconds() / 3600) if span[0] and total else None
    last24 = db.scalar(select(func.count()).where(Inspection.created_at >= datetime.now(timezone.utc) - timedelta(hours=24), *where))
    return {
        "overview": {"total": total, "passed": int(passed or 0), "review": int(review or 0), "defective": int(defective or 0), "pending_review": pend,
                     "mean_processing_ms": round(float(times.mean()), 1) if len(times) else None,
                     "p95_processing_ms": round(float(np.percentile(times, 95)), 1) if len(times) else None},
        "throughput": {"inspections_last_24h": last24, "engine_capacity_per_hour": round(3600_000 / float(times.mean())) if len(times) else None,
                       "observed_per_hour_in_window": round(total / hours, 1) if hours else None, "by_source": by_source,
                       "note": "Engine capacity = 3600 s / mean single-image processing time on this host (one worker)."},
        "by_type": [{"defect_type": t, "label": defect_label(t), "count": n, "critical": int(c or 0), "major": int(mj or 0), "minor": int(mn or 0),
                     "classified_by_model": int(ms or 0)} for t, n, c, mj, mn, ms in by_type],
        "by_material": by_material, "by_batch": by_batch, "trend": trend,
    }


@router.get("/analytics/overview")
def overview(days: int | None = Query(None, ge=1, le=3650), material: str | None = None, date_from: datetime | None = None,
             date_to: datetime | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return compute(db, window(days, material, date_from, date_to))
