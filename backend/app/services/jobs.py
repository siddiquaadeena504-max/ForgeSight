"""Background processing. A DB-backed job table + thread pool keeps the MVP single-process; the
`submit`/handler contract maps 1:1 onto Celery/RQ/Arq workers for scale-out."""
from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..config import get_settings
from ..db import SessionLocal
from ..models import Job, utcnow

log = logging.getLogger("forgesight.jobs")
_pool: ThreadPoolExecutor | None = None
HANDLERS: dict[str, Callable] = {}


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn

    return deco


def _run(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        job.status, job.started_at = "running", utcnow()
        db.commit()

        def progress(p: float, **partial):
            job.progress = float(min(1.0, max(0.0, p)))
            if partial:
                job.result = {**(job.result or {}), **partial}
            db.commit()

        try:
            result = HANDLERS[job.kind](db, job, progress)
            job.status, job.progress, job.result = "done", 1.0, {**(job.result or {}), **(result or {})}
        except Exception as exc:
            db.rollback()
            log.error("job %s failed: %s", job_id, traceback.format_exc())
            job = db.get(Job, job_id)
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()


def submit(db, kind: str, payload: dict, user_email: str | None, sync: bool = False) -> Job:
    global _pool
    job = Job(kind=kind, payload=payload, created_by=user_email)
    db.add(job)
    db.commit()
    if sync or get_settings().jobs_sync:
        _run(job.id)
        db.refresh(job)
    else:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=get_settings().job_workers, thread_name_prefix="fs-job")
        _pool.submit(_run, job.id)
    return job


def recover_orphans() -> None:
    """Jobs that were running when the process died are marked failed on startup."""
    db = SessionLocal()
    try:
        for job in db.query(Job).filter(Job.status.in_(["queued", "running"])):
            job.status, job.error, job.finished_at = "failed", "Interrupted by service restart", utcnow()
        db.commit()
    finally:
        db.close()


def job_out(j: Job) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "progress": round(j.progress, 3), "payload": {k: v for k, v in j.payload.items() if k != "storage_key"},
            "result": j.result, "error": j.error, "created_by": j.created_by, "created_at": j.created_at.isoformat(),
            "started_at": j.started_at.isoformat() if j.started_at else None, "finished_at": j.finished_at.isoformat() if j.finished_at else None}
