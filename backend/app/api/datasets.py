from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..db import get_db
from ..ml.imageops import decode_image
from ..ml.render import thumbnail
from ..models import Annotation, Dataset, DatasetImage, Inspection, Material, User, new_id
from ..security import audit, current_user, require_role
from ..services.datasets import assign_splits, export_zip, leakage_report, phash
from ..storage import get_storage, signed_url
from .inspections import read_upload

router = APIRouter(tags=["datasets"])


class DatasetIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    material_key: str = Field(max_length=64)
    description: str = Field(default="", max_length=2000)
    val_fraction: float = Field(default=0.2, ge=0, le=0.45)
    test_fraction: float = Field(default=0.2, ge=0, le=0.45)


def image_out(im: DatasetImage, with_annotations: bool = True) -> dict:
    out = {"id": im.id, "filename": im.filename, "width": im.width, "height": im.height, "split": im.split, "label": im.label, "group_key": im.group_key,
           "leak_group": im.leak_group, "source_inspection_id": im.source_inspection_id, "thumb_url": signed_url(im.thumb_key),
           "image_url": signed_url(im.image_key), "created_at": im.created_at.isoformat()}
    if with_annotations:
        out["annotations"] = [{"id": a.id, "defect_type": a.defect_type, "shape": a.shape, "bbox": a.bbox, "polygon": a.polygon, "source": a.source} for a in im.annotations]
    return out


def dataset_out(db: Session, ds: Dataset) -> dict:
    rows = db.execute(select(DatasetImage.split, DatasetImage.label, func.count()).where(DatasetImage.dataset_id == ds.id).group_by(DatasetImage.split, DatasetImage.label)).all()
    splits: dict = {}
    for split, label, n in rows:
        splits.setdefault(split, {"good": 0, "defective": 0, "unlabeled": 0})[label] = n
    classes = db.execute(select(Annotation.defect_type, func.count()).join(DatasetImage).where(DatasetImage.dataset_id == ds.id).group_by(Annotation.defect_type)).all()
    return {"id": ds.id, "name": ds.name, "material_key": ds.material_key, "description": ds.description, "val_fraction": ds.val_fraction,
            "test_fraction": ds.test_fraction, "created_by": ds.created_by, "created_at": ds.created_at.isoformat(),
            "image_count": sum(n for _, _, n in rows), "splits": splits, "defect_classes": [{"type": t, "annotations": n} for t, n in classes]}


def _get(db: Session, dataset_id: int) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found")
    return ds


@router.get("/datasets")
def list_datasets(material: str | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Dataset).order_by(Dataset.id.desc())
    if material:
        q = q.where(Dataset.material_key == material)
    return [dataset_out(db, d) for d in db.scalars(q)]


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetIn, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    if db.scalar(select(Material).where(Material.key == body.material_key)) is None:
        raise HTTPException(404, "Unknown material")
    if db.scalar(select(Dataset).where(Dataset.name == body.name)):
        raise HTTPException(409, "A dataset with this name already exists")
    ds = Dataset(**body.model_dump(), created_by=user.email)
    db.add(ds)
    db.flush()
    audit(db, user, "dataset.created", "dataset", ds.id, {"name": ds.name}, request)
    db.commit()
    return dataset_out(db, ds)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return dataset_out(db, _get(db, dataset_id))


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    ds = _get(db, dataset_id)
    st = get_storage()
    for im in ds.images:
        st.delete(im.image_key)
        if im.thumb_key:
            st.delete(im.thumb_key)
    db.delete(ds)
    audit(db, user, "dataset.deleted", "dataset", dataset_id, request=request)
    db.commit()
    return Response(status_code=204)


def add_image(db: Session, ds: Dataset, data: bytes, filename: str, label: str, group_key: str | None, source_inspection_id: str | None = None) -> DatasetImage | None:
    """Returns None when the exact same file is already in the dataset (duplicates are how leakage starts)."""
    sha = hashlib.sha256(data).hexdigest()
    if db.scalar(select(DatasetImage.id).where(DatasetImage.dataset_id == ds.id, DatasetImage.sha256 == sha)):
        return None
    img = decode_image(data)
    iid = new_id()
    ext = "png" if data[:4] == b"\x89PNG" else "jpg"
    key, tkey = f"datasets/{ds.id}/{iid}.{ext}", f"datasets/{ds.id}/{iid}_thumb.jpg"
    st = get_storage()
    st.put(key, data, f"image/{'png' if ext == 'png' else 'jpeg'}")
    st.put(tkey, thumbnail(img, 256), "image/jpeg")
    im = DatasetImage(dataset_id=ds.id, image_key=key, thumb_key=tkey, filename=filename or "", sha256=sha, phash=phash(img), width=img.shape[1],
                      height=img.shape[0], group_key=group_key or None, label=label, source_inspection_id=source_inspection_id)
    db.add(im)
    return im


@router.post("/datasets/{dataset_id}/images", status_code=201)
async def upload_images(dataset_id: int, request: Request, files: list[UploadFile] = File(...),
                        label: str = Form("unlabeled", pattern="^(good|defective|unlabeled)$"), group_key: str | None = Form(None, max_length=120),
                        user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    ds = _get(db, dataset_id)
    added, duplicates, errors = [], [], []
    for f in files:
        try:
            data = await read_upload(f, get_settings().max_upload_mb)
            im = add_image(db, ds, data, f.filename or "", label, group_key)
            (added if im else duplicates).append(im or f.filename)
        except (HTTPException, ValueError) as exc:
            errors.append({"file": f.filename, "error": getattr(exc, "detail", str(exc))})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate image detected during upload; retry")
    audit(db, user, "dataset.images_uploaded", "dataset", ds.id, {"added": len(added), "duplicates": len(duplicates), "errors": len(errors)}, request)
    db.commit()
    return {"added": [image_out(im) for im in added], "skipped_duplicates": duplicates, "errors": errors,
            "note": "New images are 'unassigned' until splits are (re)assigned."}


@router.get("/datasets/{dataset_id}/images")
def list_images(dataset_id: int, split: str | None = None, label: str | None = None, defect_type: str | None = None,
                limit: int = Query(60, ge=1, le=500), offset: int = Query(0, ge=0), _: User = Depends(current_user), db: Session = Depends(get_db)):
    _get(db, dataset_id)
    q = select(DatasetImage).where(DatasetImage.dataset_id == dataset_id)
    if split:
        q = q.where(DatasetImage.split == split)
    if label:
        q = q.where(DatasetImage.label == label)
    if defect_type:
        q = q.where(DatasetImage.id.in_(select(Annotation.image_id).where(Annotation.defect_type == defect_type)))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.options(selectinload(DatasetImage.annotations)).order_by(DatasetImage.id.desc()).limit(limit).offset(offset))
    return {"total": total, "items": [image_out(im) for im in items]}


class AnnotationIn(BaseModel):
    defect_type: str = Field(min_length=1, max_length=64)
    shape: str = Field(pattern="^(bbox|polygon)$")
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    polygon: list[list[float]] | None = None


class ImagePatch(BaseModel):
    label: str | None = Field(default=None, pattern="^(good|defective|unlabeled)$")
    group_key: str | None = Field(default=None, max_length=120)
    annotations: list[AnnotationIn] | None = None


@router.patch("/datasets/{dataset_id}/images/{image_id}")
def update_image(dataset_id: int, image_id: int, body: ImagePatch, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    im = db.scalar(select(DatasetImage).options(selectinload(DatasetImage.annotations)).where(DatasetImage.id == image_id, DatasetImage.dataset_id == dataset_id))
    if im is None:
        raise HTTPException(404, "Image not found")
    if body.group_key is not None:
        im.group_key = body.group_key or None
    if body.annotations is not None:
        im.annotations.clear()
        for a in body.annotations:
            if a.shape == "polygon":
                if not a.polygon or len(a.polygon) < 3:
                    raise HTTPException(422, "A polygon needs at least 3 points")
                xs, ys = [p[0] for p in a.polygon], [p[1] for p in a.polygon]
                bbox = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            elif a.bbox is None or a.bbox[2] <= 0 or a.bbox[3] <= 0:
                raise HTTPException(422, "A box needs positive width and height")
            else:
                bbox = a.bbox
            im.annotations.append(Annotation(defect_type=a.defect_type, shape=a.shape, bbox=[round(v, 1) for v in bbox],
                                             polygon=[[round(p[0], 1), round(p[1], 1)] for p in a.polygon] if a.polygon else None, created_by=user.email))
        if body.annotations and body.label is None:
            im.label = "defective"
    if body.label is not None:
        if body.label == "good" and im.annotations:
            raise HTTPException(422, "An image with defect annotations cannot be labelled good")
        im.label = body.label
    db.commit()
    return image_out(im)


@router.delete("/datasets/{dataset_id}/images/{image_id}", status_code=204)
def delete_image(dataset_id: int, image_id: int, _: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    im = db.scalar(select(DatasetImage).where(DatasetImage.id == image_id, DatasetImage.dataset_id == dataset_id))
    if im is None:
        raise HTTPException(404, "Image not found")
    st = get_storage()
    st.delete(im.image_key)
    if im.thumb_key:
        st.delete(im.thumb_key)
    db.delete(im)
    db.commit()
    return Response(status_code=204)


@router.post("/datasets/{dataset_id}/split")
def split_dataset(dataset_id: int, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    ds = _get(db, dataset_id)
    res = assign_splits(db, ds)
    audit(db, user, "dataset.split_assigned", "dataset", ds.id, res["splits"], request)
    db.commit()
    return {**res, "leakage": leakage_report(db, ds)}


@router.get("/datasets/{dataset_id}/leakage")
def dataset_leakage(dataset_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return leakage_report(db, _get(db, dataset_id))


@router.get("/datasets/{dataset_id}/export")
def export_dataset(dataset_id: int, request: Request, format: str = Query("coco", pattern="^(coco|yolo)$"),
                   user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    ds = _get(db, dataset_id)
    data = export_zip(db, ds, format)
    audit(db, user, "dataset.exported", "dataset", ds.id, {"format": format}, request)
    db.commit()
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="dataset_{ds.id}_{format}.zip"'})


class FromInspection(BaseModel):
    inspection_id: str


@router.post("/datasets/{dataset_id}/from-inspection", status_code=201)
def add_from_inspection(dataset_id: int, body: FromInspection, request: Request, user: User = Depends(require_role("engineer")), db: Session = Depends(get_db)):
    """Active learning: a human-reviewed inspection becomes a labelled training example.
    Only reviewed inspections are accepted so model output is never recycled as ground truth."""
    ds = _get(db, dataset_id)
    i = db.scalar(select(Inspection).options(selectinload(Inspection.defects)).where(Inspection.id == body.inspection_id))
    if i is None:
        raise HTTPException(404, "Inspection not found")
    if i.review_status not in ("confirmed", "corrected"):
        raise HTTPException(422, "Only human-reviewed inspections can be added to a dataset")
    if i.material_key != ds.material_key:
        raise HTTPException(422, f"Inspection material '{i.material_key}' does not match dataset material '{ds.material_key}'")
    im = add_image(db, ds, get_storage().get(i.image_key), i.filename or f"{i.id}.jpg", "defective" if i.final_outcome == "defective" else "good",
                   i.product_id, source_inspection_id=i.id)
    if im is None:
        raise HTTPException(409, "This image is already in the dataset")
    if i.final_outcome == "defective":
        for d in i.defects:
            if d.qc_status in ("confirmed", "corrected"):
                poly = d.data.get("polygon")
                im.annotations.append(Annotation(defect_type=d.human_type or d.defect_type, shape="polygon" if poly and len(poly) >= 3 else "bbox", bbox=d.data["bbox"],
                                                 polygon=poly, source="ai_corrected" if d.qc_status == "corrected" else "ai_confirmed", created_by=user.email))
    audit(db, user, "dataset.image_from_inspection", "dataset", ds.id, {"inspection_id": i.id}, request)
    db.commit()
    return image_out(im)
