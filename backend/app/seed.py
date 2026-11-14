"""Idempotent bootstrap: materials, admin user, default policy, and sync of the on-disk model store
(model cards, evaluation records, built-in inspection profiles) into the database."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .ml.knowledge import MATERIALS
from .ml.pipeline import DEFAULT_POLICY
from .models import EvaluationRun, InspectionProfile, Material, ModelVersion, Setting, User
from .security import hash_password

log = logging.getLogger("forgesight.seed")


def seed(db: Session) -> None:
    s = get_settings()
    for m in MATERIALS:
        if db.scalar(select(Material).where(Material.key == m["key"])) is None:
            db.add(Material(**m))
    if db.scalar(select(User).limit(1)) is None:
        db.add(User(email=s.admin_email, full_name="Administrator", password_hash=hash_password(s.admin_password), role="admin"))
        log.warning("Created bootstrap admin %s - change its password.", s.admin_email)
    if db.get(Setting, "policy") is None:
        db.add(Setting(key="policy", value=dict(DEFAULT_POLICY)))
    db.commit()
    sync_model_store(db)


def sync_model_store(db: Session) -> None:
    root = get_settings().models_dir
    if not root.exists():
        return
    for card_path in sorted(root.glob("*/*/card.json")):
        card = json.loads(card_path.read_text())
        if db.scalar(select(ModelVersion).where(ModelVersion.name == card["name"], ModelVersion.version == card["version"])) is None:
            db.add(ModelVersion(name=card["name"], version=card["version"], kind=card.get("kind", "unknown"), material_key=card.get("material"),
                                status="production", card=card, created_by="model-store"))
    for ev_path in sorted((root / "evaluations").glob("*.json")):
        for e in json.loads(ev_path.read_text()):
            row = db.scalar(select(EvaluationRun).where(EvaluationRun.eval_key == e["id"]))
            vals = dict(model_name=e["model"], model_version=e["version"], material_key=e.get("material"), dataset=e["dataset"], split=e["split"],
                        task=e["task"], n=e["n"], metrics=e["metrics"], notes=e.get("notes"), hardware=e.get("hardware"),
                        created_at=datetime.fromisoformat(e["created_at"]))
            if row is None:
                db.add(EvaluationRun(eval_key=e["id"], **vals))
            elif row.created_at.isoformat()[:19] != e["created_at"][:19]:
                for k, v in vals.items():
                    setattr(row, k, v)
    for prof_path in sorted((root / "profiles").glob("*.json")):
        p = json.loads(prof_path.read_text())
        row = db.scalar(select(InspectionProfile).where(InspectionProfile.key == p["key"]))
        cfg = {k: p[k] for k in ("detectors", "decision", "requires_reference", "mm_per_pixel", "drift_reference", "severity") if k in p}
        if row is None:
            db.add(InspectionProfile(key=p["key"], material_key=p["material"], name=p["name"], product_category=p.get("product_category", ""), config=cfg, builtin=True))
        elif row.builtin and row.config.get("decision", {}).get("evidence") == cfg.get("decision", {}).get("evidence") and row.config != cfg and not row.config.get("edited"):
            row.config = cfg
    db.commit()
