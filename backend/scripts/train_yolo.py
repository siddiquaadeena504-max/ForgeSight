"""Train an Ultralytics YOLO detector on box-labelled data and register it in the model store.

Two sources:
  --deeppcb            export the DeepPCB public dataset (test images only; no template needed at inference)
  --zip dataset.zip    a YOLO export from Dataset Management (Export -> YOLO)

No pretrained YOLO weights ship with the platform. By default the model is built from the
architecture YAML and trained from scratch; pass --weights yolov8n.pt (if you have the file or
internet access to Ultralytics' release assets) for transfer learning, which is strongly recommended.

Example (GPU):  python scripts/train_yolo.py --deeppcb --name pcb_yolo --epochs 100 --imgsz 640
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[2]


def export_deeppcb(out: Path, limit: int | None) -> list[str]:
    from app.ml import public_datasets as D

    samples = D.load_deeppcb()
    for split in ("train", "val", "test"):
        (out / split / "images").mkdir(parents=True, exist_ok=True)
        (out / split / "labels").mkdir(parents=True, exist_ok=True)
        sel = [s for s in samples if s.split == split]
        for s in sel[:limit] if limit else sel:
            stem = Path(s.path).stem
            shutil.copy(s.path, out / split / "images" / f"{stem}.jpg")
            lines = [f"{D.PCB_CLASSES.index(c)} {(x + w / 2) / 640:.6f} {(y + h / 2) / 640:.6f} {w / 640:.6f} {h / 640:.6f}" for x, y, w, h, c in s.boxes]
            (out / split / "labels" / f"{stem}.txt").write_text("\n".join(lines))
    (out / "data.yaml").write_text(f"path: {out}\ntrain: train/images\nval: val/images\ntest: test/images\nnames:\n" +
                                   "".join(f"  {i}: {c}\n" for i, c in enumerate(D.PCB_CLASSES)))
    return D.PCB_CLASSES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deeppcb", action="store_true")
    ap.add_argument("--zip", type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--material", default="electronics")
    ap.add_argument("--weights", default="yolov8n.yaml", help="architecture yaml (from scratch) or a .pt file (transfer learning)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--limit", type=int, default=None, help="max images per split (smoke tests)")
    a = ap.parse_args()

    from ultralytics import YOLO

    work = ROOT / "data" / "yolo_work" / a.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    if a.deeppcb:
        export_deeppcb(work, a.limit)
        dataset = "DeepPCB (official split, 20% of trainval as validation)"
    elif a.zip:
        zipfile.ZipFile(a.zip).extractall(work)
        yaml = (work / "data.yaml").read_text().replace("path: .", f"path: {work}")
        (work / "data.yaml").write_text(yaml)
        dataset = f"managed dataset export {a.zip.name}"
    else:
        ap.error("choose --deeppcb or --zip")

    model = YOLO(a.weights)
    model.train(data=str(work / "data.yaml"), epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, project=str(work / "runs"), name="train",
                exist_ok=True, plots=False, amp=False, workers=2, verbose=False)
    best = work / "runs" / "train" / "weights" / "best.pt"
    test = YOLO(str(best)).val(data=str(work / "data.yaml"), split="test", imgsz=a.imgsz, plots=False, verbose=False, project=str(work / "runs"), name="test", exist_ok=True)
    metrics = {"test": {"precision": round(float(test.box.mp), 4), "recall": round(float(test.box.mr), 4), "mAP50": round(float(test.box.map50), 4),
                        "mAP50_95": round(float(test.box.map), 4)}}
    dest = ROOT / "data" / "models" / a.name / a.version
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(best, dest / "weights.pt")
    n_train = len(list((work / "train" / "images").glob("*")))
    n_test = len(list((work / "test" / "images").glob("*")))
    card = {"name": a.name, "version": a.version, "kind": "detection", "material": a.material, "architecture": f"Ultralytics YOLO ({a.weights})",
            "dataset": dataset, "splits": {"train": n_train, "test": n_test}, "training": {"epochs": a.epochs, "imgsz": a.imgsz, "from_scratch": a.weights.endswith(".yaml")},
            "metrics": metrics, "limitations": ["Trained from scratch (no pretrained weights) unless --weights *.pt was supplied.",
                                                f"Only {a.epochs} epoch(s) on {n_train} images." if a.epochs < 50 else "Validated on its own dataset only."],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (dest / "card.json").write_text(json.dumps(card, indent=2))
    print(json.dumps(metrics))
    print(f"Registered {dest}. Restart the API (or it syncs on next start), then add a detector entry "
          f'{{"type": "yolo", "model": "{a.name}", "version": "{a.version}"}} to an inspection profile.')


if __name__ == "__main__":
    main()
