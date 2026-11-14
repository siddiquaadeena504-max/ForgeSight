from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import admin, analytics, auth, catalog, datasets, inspections, live, models_api, reports
from .config import get_settings
from .db import Base, SessionLocal, engine
from .seed import seed
from .services.jobs import recover_orphans

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("forgesight")


def init_db() -> None:
    s = get_settings()
    if s.run_migrations and not s.database_url.startswith("sqlite"):
        from alembic import command
        from alembic.config import Config
        from pathlib import Path

        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(cfg, "head")
    else:
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.env == "production" and s.secret_key.startswith("dev-only"):
        raise RuntimeError("FS_SECRET_KEY must be set in production")
    init_db()
    recover_orphans()
    yield


app = FastAPI(title="ForgeSight - Manufacturing Defect Inspection API", version="1.0.0", lifespan=lifespan,
              description="Universal, profile-driven visual inspection. All endpoints except /api/health and /api/auth/login require a bearer token.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "; ".join(f"{e['field']}: {e['message']}" for e in errs), "errors": errs})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error. The incident was logged."})


for r in (auth.router, inspections.router, catalog.router, datasets.router, models_api.router, analytics.router, reports.router, live.router, admin.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok"}
