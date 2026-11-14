"""Run held-out TEST images of the public datasets through the live inspection pipeline and store
them as inspections (source = "benchmark", with ground truth). These are real pipeline outputs on
real images: they populate the dashboards and feed the production-monitoring view.
Nothing here is synthetic and no result is edited. Timestamps are the actual processing times.

Usage: python scripts/replay_benchmark.py [--pcb 120] [--mt 400] [--cfd 40]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import init_db  # noqa: E402
from app.ml import public_datasets as D  # noqa: E402
from app.models import Inspection, InspectionProfile  # noqa: E402
from app.services.inspection import run_inspection  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", type=int, default=120)
    ap.add_argument("--mt", type=int, default=400)
    ap.add_argument("--cfd", type=int, default=40)
    a = ap.parse_args()
    init_db()
    db = SessionLocal()
    if db.scalar(select(func.count()).where(Inspection.source == "benchmark")):
        print("Benchmark replay already present; skipping.")
        return
    have = {p.key for p in db.scalars(select(InspectionProfile))}
    jobs = []
    if "magnetic_tile" in have:
        mt = [s for s in D.load_magnetic_tile() if s.split == "test"][: a.mt]
        for i, s in enumerate(mt):  # arbitrary lots of 40 images, named as replay lots
            jobs.append((s, "magnetic_tile", f"MT-REPLAY-{i // 40 + 1:02d}", "good" if s.label == "good" else "defective", None))
    if "pcb_bare_board" in have:
        pcb = [s for s in D.load_deeppcb() if s.split == "test"][: a.pcb]
        for s in pcb:  # the batch is the real board group of the dataset
            jobs.append((s, "pcb_bare_board", f"PCB-{s.group.replace('group', '')}", "defective", s.ref_path))
    if "pavement_crack" in have:
        for s in [s for s in D.load_crackforest() if s.split == "test"][: a.cfd]:
            jobs.append((s, "pavement_crack", "CFD-REPLAY-01", "defective", None))
    for n, (s, profile, batch, gt, ref) in enumerate(jobs, 1):
        insp, _ = run_inspection(db, image_bytes=Path(s.path).read_bytes(), filename=Path(s.path).name, user_email="benchmark-replay",
                                 profile_key=profile, batch_id=batch, product_id=Path(s.path).stem, source="benchmark", ground_truth=gt,
                                 reference_bytes=Path(ref).read_bytes() if ref else None)
        if n % 50 == 0 or n == len(jobs):
            print(f"{n}/{len(jobs)} last: {profile} gt={gt} -> {insp.outcome}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
