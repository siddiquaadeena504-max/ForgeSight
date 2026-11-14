from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # viewer | inspector | engineer | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    family: Mapped[str] = mapped_column(String(64), default="generic")
    description: Mapped[str] = mapped_column(Text, default="")
    common_defects: Mapped[list] = mapped_column(JSON, default=list)
    imaging_notes: Mapped[str] = mapped_column(Text, default="")
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)


class InspectionProfile(Base):
    __tablename__ = "inspection_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    material_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    product_category: Mapped[str] = mapped_column(String(255), default="")
    config: Mapped[dict] = mapped_column(JSON)  # detectors, decision, mm_per_pixel, severity, drift_reference
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(40))
    material_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate | production | archived
    card: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    eval_key: Mapped[str] = mapped_column(String(160), unique=True)
    model_name: Mapped[str] = mapped_column(String(120), index=True)
    model_version: Mapped[str] = mapped_column(String(40))
    material_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset: Mapped[str] = mapped_column(String(255))
    split: Mapped[str] = mapped_column(String(20))
    task: Mapped[str] = mapped_column(String(255))
    n: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hardware: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (Index("ix_insp_created_outcome", "created_at", "outcome"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    material_key: Mapped[str] = mapped_column(String(64), index=True)
    material_source: Mapped[str] = mapped_column(String(20), default="user")  # user | suggested | override
    material_suggestion: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    profile_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="upload", index=True)  # upload | video | live | benchmark
    job_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="done")
    outcome: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)  # AI: pass | review | defective
    final_outcome: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)  # after human review
    p_defect: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    defect_count: Mapped[int] = mapped_column(Integer, default=0)
    max_severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    processing_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    image_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    annotated_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    heatmap_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thumb_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    ground_truth: Mapped[str | None] = mapped_column(String(40), nullable=True)  # only for labelled replays
    review_status: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)  # pending | confirmed | corrected
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    defects: Mapped[list["Defect"]] = relationship(back_populates="inspection", cascade="all, delete-orphan", order_by="Defect.idx")


class Defect(Base):
    __tablename__ = "defects"
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[str] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    defect_type: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64))
    type_source: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    data: Mapped[dict] = mapped_column(JSON)  # full finding (bbox, polygon, dimensions, hypotheses, ...)
    qc_status: Mapped[str] = mapped_column(String(20), default="open")  # open | confirmed | rejected | corrected
    human_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inspection: Mapped[Inspection] = relationship(back_populates="defects")


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    material_key: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    split_seed: Mapped[str] = mapped_column(String(32), default="v1")
    val_fraction: Mapped[float] = mapped_column(Float, default=0.2)
    test_fraction: Mapped[float] = mapped_column(Float, default=0.2)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    images: Mapped[list["DatasetImage"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class DatasetImage(Base):
    __tablename__ = "dataset_images"
    __table_args__ = (UniqueConstraint("dataset_id", "sha256", name="uq_dataset_sha"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    image_key: Mapped[str] = mapped_column(String(255))
    thumb_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str] = mapped_column(String(16))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    group_key: Mapped[str | None] = mapped_column(String(120), nullable=True)  # serial / batch: kept in one split
    leak_group: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # resolved group id
    split: Mapped[str] = mapped_column(String(12), default="unassigned", index=True)
    label: Mapped[str] = mapped_column(String(12), default="unlabeled", index=True)  # good | defective | unlabeled
    source_inspection_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dataset: Mapped[Dataset] = relationship(back_populates="images")
    annotations: Mapped[list["Annotation"]] = relationship(back_populates="image", cascade="all, delete-orphan")


class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("dataset_images.id", ondelete="CASCADE"), index=True)
    defect_type: Mapped[str] = mapped_column(String(64), index=True)
    shape: Mapped[str] = mapped_column(String(10))  # bbox | polygon
    bbox: Mapped[list] = mapped_column(JSON)  # x, y, w, h
    polygon: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="human")  # human | ai_confirmed | ai_corrected
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[DatasetImage] = relationship(back_populates="annotations")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued | running | done | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
