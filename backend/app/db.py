from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_kw = {"connect_args": {"check_same_thread": False}} if _settings.database_url.startswith("sqlite") else {"pool_pre_ping": True, "pool_size": 10}
engine = create_engine(_settings.database_url, **_kw)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
