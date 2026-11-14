from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import EvaluationRun, Inspection, Material, User
from ..security import audit, current_user
from ..services import reports as R
from .analytics import compute, window
from .inspections import apply_filters
from .models_api import headline

router = APIRouter(tags=["reports"])
MAX_ROWS = 20000


def _load(db: Session, inspection_id: str) -> Inspection:
    i = db.scalar(select(Inspection).options(selectinload(Inspection.defects)).where(Inspection.id == inspection_id))
    if i is None:
        raise HTTPException(404, "Inspection not found")
    return i


def _dl(data: bytes, media: str, name: str) -> Response:
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/reports/inspections/{inspection_id}.pdf")
def inspection_pdf(inspection_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _load(db, inspection_id)
    name = db.scalar(select(Material.name).where(Material.key == i.material_key)) or i.material_key
    audit(db, user, "report.inspection_pdf", "inspection", i.id, request=request)
    db.commit()
    return _dl(R.inspection_pdf(i, name), "application/pdf", f"inspection_{i.id}.pdf")


@router.get("/reports/inspections/{inspection_id}.csv")
def inspection_csv(inspection_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _load(db, inspection_id)
    return _dl(R.to_csv(R.DEFECT_COLUMNS, R.defect_rows(i)), "text/csv", f"inspection_{i.id}_defects.csv")


def _filtered(db, **kw):
    q = apply_filters(select(Inspection).options(selectinload(Inspection.defects)), **kw).order_by(Inspection.created_at.desc()).limit(MAX_ROWS)
    return list(db.scalars(q))


@router.get("/reports/inspections.csv")
def inspections_csv(request: Request, outcome: str | None = None, material: str | None = None, batch: str | None = None, source: str | None = None,
                    date_from: datetime | None = None, date_to: datetime | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = _filtered(db, outcome=outcome, material=material, batch=batch, source=source, date_from=date_from, date_to=date_to)
    audit(db, user, "report.inspections_csv", detail={"rows": len(rows)}, request=request)
    db.commit()
    return _dl(R.to_csv(R.INSPECTION_COLUMNS, [R.inspection_row(i) for i in rows]), "text/csv", "inspections.csv")


@router.get("/reports/defects.csv")
def defects_csv(outcome: str | None = None, material: str | None = None, batch: str | None = None, source: str | None = None,
                date_from: datetime | None = None, date_to: datetime | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = _filtered(db, outcome=outcome, material=material, batch=batch, source=source, date_from=date_from, date_to=date_to)
    return _dl(R.to_csv(R.DEFECT_COLUMNS, [r for i in rows for r in R.defect_rows(i)]), "text/csv", "defects.csv")


@router.get("/reports/quality.pdf")
def quality_pdf(request: Request, days: int | None = Query(None, ge=1, le=3650), material: str | None = None, date_from: datetime | None = None,
                date_to: datetime | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = compute(db, window(days, material, date_from, date_to))
    evals = []
    for e in db.scalars(select(EvaluationRun).order_by(EvaluationRun.material_key)):
        h = headline(e)
        evals.append({"model": e.model_name, "version": e.model_version, "dataset": e.dataset, "split": e.split, "task": e.task, "n": e.n,
                      "headline": "; ".join(f"{x['label']} {x['value']}" for x in h[:4]) or "see model card"})
    period = (f"{date_from:%Y-%m-%d} to {date_to:%Y-%m-%d}" if date_from and date_to else f"Last {days} days" if days else "All time") + (f" - material: {material}" if material else "")
    audit(db, user, "report.quality_pdf", detail={"period": period}, request=request)
    db.commit()
    return _dl(R.quality_pdf("Quality Control Report", period, a["overview"], a["by_type"], a["by_material"], a["by_batch"], a["trend"], evals),
               "application/pdf", "quality_report.pdf")
