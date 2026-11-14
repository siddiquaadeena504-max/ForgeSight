"""Dataset management: perceptual hashing, leakage-safe splits, export."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Dataset, DatasetImage
from ..storage import get_storage

NEAR_DUP_BITS = 4  # Hamming distance (of 64) at or below which two images are treated as the same part/view


def phash(img: np.ndarray) -> str:
    """64-bit DCT perceptual hash."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    d = cv2.dct(g)[:8, :8].flatten()
    bits = d > np.median(d[1:])
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def resolve_groups(images: list[DatasetImage]) -> dict[int, str]:
    """Union-find over (a) explicit group keys and (b) near-duplicate perceptual hashes.
    Every image in a group must live in the same split, otherwise evaluation leaks."""
    parent = {im.id: im.id for im in images}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_key: dict[str, int] = {}
    for im in images:
        if im.group_key:
            if im.group_key in by_key:
                union(im.id, by_key[im.group_key])
            else:
                by_key[im.group_key] = im.id
    if images:
        hashes = np.array([int(im.phash, 16) for im in images], dtype=np.uint64)
        ids = [im.id for im in images]
        for i in range(len(images)):
            x = np.bitwise_xor(hashes[i + 1 :], hashes[i])
            dist = np.array([int(v).bit_count() for v in x]) if len(x) else np.array([])
            for j in np.flatnonzero(dist <= NEAR_DUP_BITS):
                union(ids[i], ids[i + 1 + int(j)])
    sha = {im.id: im.sha256 for im in images}
    roots: dict[int, list[int]] = {}
    for im in images:
        roots.setdefault(find(im.id), []).append(im.id)
    out = {}
    for members in roots.values():
        gid = hashlib.sha256("|".join(sorted(sha[m] for m in members)).encode()).hexdigest()[:16]
        for m in members:
            out[m] = gid
    return out


def _bucket(key: str, seed: str) -> float:
    return int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def assign_splits(db: Session, ds: Dataset) -> dict:
    images = list(db.scalars(select(DatasetImage).where(DatasetImage.dataset_id == ds.id)))
    groups = resolve_groups(images)
    # Deterministic: a group always hashes to the same split for a given seed, so re-running never moves test data into training.
    counts = {"train": 0, "val": 0, "test": 0}
    for im in images:
        gid = groups[im.id]
        b = _bucket(gid, ds.split_seed)
        im.leak_group = gid
        im.split = "test" if b < ds.test_fraction else "val" if b < ds.test_fraction + ds.val_fraction else "train"
        counts[im.split] += 1
    db.commit()
    return {"images": len(images), "groups": len(set(groups.values())), "multi_image_groups": sum(1 for g in set(groups.values()) if list(groups.values()).count(g) > 1),
            "splits": counts}


def leakage_report(db: Session, ds: Dataset) -> dict:
    images = list(db.scalars(select(DatasetImage).where(DatasetImage.dataset_id == ds.id)))
    groups = resolve_groups(images)
    by_group: dict[str, list[DatasetImage]] = {}
    for im in images:
        by_group.setdefault(groups[im.id], []).append(im)
    leaks = []
    for gid, members in by_group.items():
        splits = {m.split for m in members if m.split != "unassigned"}
        if len(splits) > 1:
            leaks.append({"group": gid, "splits": sorted(splits), "images": [{"id": m.id, "filename": m.filename, "split": m.split} for m in members]})
    unassigned = sum(1 for im in images if im.split == "unassigned")
    return {"clean": not leaks, "leaking_groups": leaks, "unassigned_images": unassigned, "images": len(images),
            "method": f"explicit group keys + perceptual-hash near-duplicates (Hamming <= {NEAR_DUP_BITS}/64) + exact SHA-256"}


def export_zip(db: Session, ds: Dataset, fmt: str = "coco") -> bytes:
    """COCO (one json per split) or YOLO (labels/*.txt + data.yaml). Images are stored under <split>/."""
    st = get_storage()
    images = list(db.scalars(select(DatasetImage).where(DatasetImage.dataset_id == ds.id).order_by(DatasetImage.id)))
    classes = sorted({a.defect_type for im in images for a in im.annotations})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        coco = {s: {"images": [], "annotations": [], "categories": [{"id": i + 1, "name": c} for i, c in enumerate(classes)]} for s in ("train", "val", "test", "unassigned")}
        ann_id = 1
        manifest = []
        for im in images:
            ext = im.image_key.rsplit(".", 1)[-1]
            name = f"{im.id:07d}.{ext}"
            z.writestr(f"{im.split}/images/{name}", st.get(im.image_key))
            manifest.append({"file": f"{im.split}/images/{name}", "original_filename": im.filename, "split": im.split, "label": im.label,
                             "group": im.leak_group, "sha256": im.sha256})
            if fmt == "yolo":
                lines = []
                for a in im.annotations:
                    x, y, w, h = a.bbox
                    lines.append(f"{classes.index(a.defect_type)} {(x + w / 2) / im.width:.6f} {(y + h / 2) / im.height:.6f} {w / im.width:.6f} {h / im.height:.6f}")
                z.writestr(f"{im.split}/labels/{name.rsplit('.', 1)[0]}.txt", "\n".join(lines))
            else:
                c = coco[im.split]
                c["images"].append({"id": im.id, "file_name": f"images/{name}", "width": im.width, "height": im.height, "label": im.label})
                for a in im.annotations:
                    seg = [[float(v) for pt in a.polygon for v in pt]] if a.polygon else []
                    c["annotations"].append({"id": ann_id, "image_id": im.id, "category_id": classes.index(a.defect_type) + 1, "bbox": a.bbox,
                                             "area": a.bbox[2] * a.bbox[3], "segmentation": seg, "iscrowd": 0})
                    ann_id += 1
        if fmt == "yolo":
            z.writestr("data.yaml", f"path: .\ntrain: train/images\nval: val/images\ntest: test/images\nnames:\n" + "".join(f"  {i}: {c}\n" for i, c in enumerate(classes)))
        else:
            for s, c in coco.items():
                if c["images"]:
                    z.writestr(f"{s}/annotations.json", json.dumps(c))
        z.writestr("manifest.json", json.dumps({"dataset": ds.name, "material": ds.material_key, "classes": classes, "format": fmt, "images": manifest}, indent=1))
    return buf.getvalue()
