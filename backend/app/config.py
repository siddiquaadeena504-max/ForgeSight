from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FS_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://forgesight:forgesight@localhost:5432/forgesight"
    secret_key: str = "dev-only-change-me-dev-only-change-me"
    access_token_minutes: int = 480
    file_url_ttl_seconds: int = 3600
    cors_origins: str = "http://localhost:3000"

    storage_backend: str = "local"  # local | s3
    storage_dir: Path = ROOT / "data" / "storage"
    s3_bucket: str = "forgesight"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    models_dir: Path = ROOT / "data" / "models"
    max_upload_mb: int = 25
    max_video_mb: int = 300
    job_workers: int = 2
    jobs_sync: bool = False  # run jobs inline (tests)

    admin_email: str = "admin@forgesight.local"
    admin_password: str = "ChangeMe!2026"
    run_migrations: bool = True

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, v: str) -> str:
        # Hosting providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
