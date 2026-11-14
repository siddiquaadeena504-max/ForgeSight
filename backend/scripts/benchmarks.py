"""Train + validate the shipped models on public datasets and write model cards / evaluation records.

Every number written by this script is measured on a held-out split. Nothing is copied from papers.
Usage:  python scripts/benchmarks.py [pcb] [mt] [cfd] [material]      (default: all stages)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ml import metrics as M  # noqa: E402
from app.ml import public_datasets as D  # noqa: E402
from app.ml.calibration import Platt, select_review_band  # noqa: E402
from app.ml.detectors.classical import ClassicalDetector  # noqa: E402
from app.ml.detectors.patchcore import PatchCore  # noqa: E402
from app.ml.detectors.refdiff import ReferenceDiffDetector, crop_pair  # noqa: E402
from app.ml.detectors.segnet import SegDetector  # noqa: E402
from app.ml.imageops import bbox_iou, to_gray  # noqa: E402
from app.ml.training import train_cropnet, train_segnet  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "data" / "models"
VERSION = "1.0.0"
torch.set_num_threads(4)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))


def record(evals: list, **kw):
    kw.setdefault("created_at", now())
    kw.setdefault("hardware", f"CPU x{torch.get_num_threads()} threads (no GPU)")
    evals.append(kw)


def flush_evals(stage: str, evals: list):
    write_json(OUT / "evaluations" / f"{stage}.json", evals)


def split_counts(samples):
    out: dict = {}
    for s in samples:
        out.setdefault(s.split, {}).setdefault(s.label, 0)
        out[s.split][s.label] += 1
    return out


# ============================================================================================ PCB
def match_boxes(pred: list, gt: list, thr: float = 0.33):
    """Greedy one-to-one matching. -> list of (pred_idx, gt_idx)."""
    pairs = sorted(((bbox_iou(p, g), i, j) for i, p in enumerate(pred) for j, g in enumerate(gt)), reverse=True)
    used_p, used_g, out = set(), set(), []
    for iou, i, j in pairs:
        if iou < thr:
            break
        if i in used_p or j in used_g:
            continue
        used_p.add(i), used_g.add(j), out.append((i, j))
    return out


def stage_pcb():
    evals: list = []
    samples = D.load_deeppcb()
    tr = [s for s in samples if s.split == "train"]
    va = [s for s in samples if s.split == "val"]
    te = [s for s in samples if s.split == "test"]
    log(f"DeepPCB: train {len(tr)} val {len(va)} test {len(te)}")

    def read(s):
        return cv2.imread(s.path, 0), cv2.imread(s.ref_path, 0)

    # --- tune the proposal stage on validation (class-agnostic F1 @ IoU 0.33)
    best = None
    for thr in (50, 90):
        for min_area in (8, 20):
            for merge in (2, 5):
                for pad in (4, 8, 12):
                    det = ReferenceDiffDetector(thr, min_area, align=False, merge_px=merge, box_pad=pad)
                    tp = fp = fn = 0
                    for s in va[:60]:
                        t, r = read(s)
                        boxes = [x.bbox for x in det.propose(t, r)]
                        m = match_boxes(boxes, [b[:4] for b in s.boxes])
                        tp, fp, fn = tp + len(m), fp + len(boxes) - len(m), fn + len(s.boxes) - len(m)
                    f1 = 2 * tp / max(1, 2 * tp + fp + fn)
                    if best is None or f1 > best[0]:
                        best = (f1, thr, min_area, merge, pad)
    log("proposal tuning (val):", best)
    _, thr, min_area, merge, pad = best
    classes = D.PCB_CLASSES + ["false_alarm"]
    det = ReferenceDiffDetector(thr, min_area, align=False, merge_px=merge, classes=classes, box_pad=pad, name="pcb_refdiff", version=VERSION)

    # --- classifier training set: proposals labelled by GT match (+ missed GT boxes)
    def crops_for(split):
        X, y = [], []
        for s in split:
            t, r = read(s)
            regs = det.propose(t, r)
            m = dict(match_boxes([x.bbox for x in regs], [b[:4] for b in s.boxes]))
            matched_gt = set(m.values())
            for i, reg in enumerate(regs):
                X.append(crop_pair(t, r, reg.bbox))
                y.append(classes.index(s.boxes[m[i]][4]) if i in m else len(classes) - 1)
            for j, b in enumerate(s.boxes):
                if j not in matched_gt:
                    X.append(crop_pair(t, r, b[:4]))
                    y.append(classes.index(b[4]))
        return np.stack(X), np.array(y)

    Xtr, ytr = crops_for(tr)
    log("crops:", Xtr.shape, np.bincount(ytr))
    net, tlog = train_cropnet(len(classes), Xtr, ytr, epochs=14, log=log)
    det.classifier = net

    def evaluate(split):
        tp = fp = fn = tp_c = 0
        loc_tp = loc_fp = 0
        y_true, y_pred, lat = [], [], []
        fa_per_image = []
        per_cls_tp = {c: 0 for c in D.PCB_CLASSES}
        per_cls_gt = {c: 0 for c in D.PCB_CLASSES}
        per_cls_pred = {c: 0 for c in D.PCB_CLASSES}
        from app.ml.types import InspectionContext
        for s in split:
            img = cv2.imread(s.path)
            out = det.predict(img, InspectionContext("electronics", {}, reference_bgr=cv2.imread(s.ref_path)))
            lat.append(out.latency_ms)
            m = match_boxes([r.bbox for r in out.regions], [b[:4] for b in s.boxes])
            tp, fp, fn = tp + len(m), fp + len(out.regions) - len(m), fn + len(s.boxes) - len(m)
            fa_per_image.append(len(out.regions) - len(m))
            for b in s.boxes:
                per_cls_gt[b[4]] += 1
            for r in out.regions:
                per_cls_pred[r.defect_type] += 1
            for i, j in m:
                y_true.append(s.boxes[j][4]), y_pred.append(out.regions[i].defect_type)
                if s.boxes[j][4] == out.regions[i].defect_type:
                    tp_c += 1
                    per_cls_tp[s.boxes[j][4]] += 1
        n_pred, n_gt = tp + fp, tp + fn
        return {
            "images": len(split), "gt_defects": n_gt, "predicted_defects": n_pred,
            "localization": {"iou_threshold": 0.33, "precision": round(tp / max(1, n_pred), 4), "recall": round(tp / max(1, n_gt), 4),
                             "recall_ci95": M.wilson(tp, n_gt), "f1": round(2 * tp / max(1, n_pred + n_gt), 4),
                             "false_negative_rate": round(fn / max(1, n_gt), 4), "false_alarms_per_image": round(float(np.mean(fa_per_image)), 4)},
            "class_aware": {"precision": round(tp_c / max(1, n_pred), 4), "recall": round(tp_c / max(1, n_gt), 4), "recall_ci95": M.wilson(tp_c, n_gt),
                            "f1": round(2 * tp_c / max(1, n_pred + n_gt), 4)},
            "per_defect": {c: {"support": per_cls_gt[c], "recall": round(per_cls_tp[c] / max(1, per_cls_gt[c]), 4),
                               "recall_ci95": M.wilson(per_cls_tp[c], per_cls_gt[c]),
                               "precision": round(per_cls_tp[c] / max(1, per_cls_pred[c]), 4)} for c in D.PCB_CLASSES},
            "classification_of_matched": M.multiclass_report(y_true, y_pred, D.PCB_CLASSES),
            "latency_ms_mean": round(float(np.mean(lat)), 1), "latency_ms_p95": round(float(np.percentile(lat, 95)), 1),
        }

    val_m, test_m = evaluate(va), evaluate(te)
    log("PCB test:", json.dumps({k: test_m[k] for k in ("localization", "class_aware")}))
    det.save(OUT / "pcb_refdiff" / VERSION / "model.pt")
    limitations = [
        "Requires an aligned defect-free template of the same board region (golden-reference inspection).",
        "DeepPCB images are binarized line-scan crops at ~48 px/mm; photographs of populated boards are out of distribution.",
        "DeepPCB contains no defect-free test images, so image-level false-positive rate and AUROC cannot be measured; "
        "only defect-level precision/recall are validated. Automatic PASS is therefore disabled for this profile by default.",
        "Most DeepPCB defects were synthetically added by the dataset authors following real defect patterns.",
        "The official trainval/test split shares board groups between splits (we keep it for comparability).",
    ]
    card = {
        "name": "pcb_refdiff", "version": VERSION, "kind": "reference", "architecture": "template differencing + CropNet (4-block CNN, 2-channel 64x64 crops)",
        "material": "electronics", "classes": D.PCB_CLASSES, "dataset": "DeepPCB (official split; 20% of trainval held out for validation)",
        "splits": {"train": len(tr), "val": len(va), "test": len(te)}, "proposal_params": {"diff_threshold": thr, "min_area": min_area, "merge_px": merge, "box_pad": pad},
        "training": tlog, "metrics": {"val": val_m, "test": test_m}, "limitations": limitations, "created_at": now(),
    }
    write_json(OUT / "pcb_refdiff" / VERSION / "card.json", card)
    record(evals, id="pcb_refdiff-test", model="pcb_refdiff", version=VERSION, material="electronics", dataset="DeepPCB", split="test",
           task="defect detection + classification (reference comparison)", n=test_m["images"], metrics=test_m, notes=limitations)
    write_json(OUT / "profiles" / "pcb_bare_board.json", {
        "key": "pcb_bare_board", "material": "electronics", "name": "Bare PCB - golden template comparison",
        "product_category": "Printed circuit board (bare, binarized AOI image)", "requires_reference": True, "mm_per_pixel": round(1 / 48, 5),
        "detectors": [{"type": "refdiff", "model": "pcb_refdiff", "version": VERSION}],
        "decision": {"mode": "regions", "region_confident": 0.9, "image_level_validated": False, "validated": True,
                     "evidence": "pcb_refdiff-test"},
    })
    flush_evals("pcb", evals)


# ============================================================================================= MT
def stage_mt():
    evals: list = []
    samples = D.load_magnetic_tile()
    samples, dropped = D.drop_cross_split_duplicates(samples)
    log(f"MT: {len(samples)} samples, {dropped} cross-split exact duplicates dropped; splits {split_counts(samples)}")
    imgs = [s.image() for s in samples]
    y = np.array([0 if s.label == "good" else 1 for s in samples])
    split = np.array([s.split for s in samples])
    tr, va, te = split == "train", split == "val", split == "test"

    # ---------------- PatchCore (unsupervised, good-only training)
    pc = PatchCore(name="mt_patchcore", version=VERSION)
    t0 = time.time()
    emb = pc.embed_many(imgs)
    log(f"embedded {tuple(emb.shape)} in {time.time() - t0:.0f}s")
    pc.fit_embeddings(emb[torch.from_numpy(tr & (y == 0))], coreset=4000)
    dmaps = pc.distance_maps(emb)
    pc_score = np.array([pc.image_score(d) for d in dmaps])
    # pixel threshold on validation defects (max pixel-F1), evaluated at image resolution
    cand = np.quantile(np.concatenate([d.ravel() for d in dmaps[va & (y == 0)]]), [0.99, 0.995, 0.999, 0.9995, 0.9999])

    def pc_pixels(mask_sel, thr):
        gts, prs = [], []
        for i in np.flatnonzero(mask_sel):
            g = D.mt_mask(samples[i])
            gts.append(g.ravel()), prs.append((pc.full_map(dmaps[i], *g.shape) > thr).ravel())
        return M.pixel_report(np.concatenate(gts), np.concatenate(prs))

    scores = [(pc_pixels(va & (y == 1), t)["pixel_f1"] or 0, float(t)) for t in cand]
    pc.pixel_threshold = max(scores)[1]
    pc.score_scale = 2 * pc.pixel_threshold
    log("patchcore pixel threshold candidates (val pixel-F1):", scores)
    pc_platt = Platt.fit(pc_score[va], y[va])
    pc.save(OUT / "mt_patchcore" / VERSION / "model.pt")

    # 5-fold cross-validation of PatchCore image-level AUROC over the full dataset
    fold = np.array([int(D._bucket(s.group, "mt-cv") * 5) % 5 for s in samples])
    cv = []
    for k in range(5):
        m = PatchCore()
        m.fit_embeddings(emb[torch.from_numpy((fold != k) & (y == 0))], coreset=2500, seed=k)
        sel = fold == k
        sc = [m.image_score(d) for d in m.distance_maps(emb[torch.from_numpy(sel)])]
        cv.append(M.auroc(y[sel], sc))
        log(f"  CV fold {k}: AUROC {cv[-1]} (n={int(sel.sum())})")
    cv_res = {"folds": 5, "auroc_per_fold": cv, "auroc_mean": round(float(np.mean(cv)), 4), "auroc_std": round(float(np.std(cv)), 4)}

    # ---------------- SegNet (supervised, pixel labels)
    seg = SegDetector(D.MT_CLASSES, input_size=(320, 320), name="mt_segnet", version=VERSION)
    masks = [D.mt_mask(s) * (D.MT_CLASSES.index(s.label) + 1 if s.label != "good" else 0) for s in samples]
    tlog = train_segnet(seg, [imgs[i] for i in np.flatnonzero(tr)], [masks[i] for i in np.flatnonzero(tr)], epochs=36, log=log)
    probs = np.concatenate([seg.prob_maps(imgs[i : i + 16]) for i in range(0, len(imgs), 16)])
    seg_score = np.array([seg.image_score_from_prob(1 - p[0]) for p in probs])

    def seg_pixels(mask_sel, thr):
        gts, prs = [], []
        for i in np.flatnonzero(mask_sel):
            g = D.mt_mask(samples[i])
            pr = cv2.resize((1 - probs[i][0]).astype(np.float32), (g.shape[1], g.shape[0])) > thr
            gts.append(g.ravel()), prs.append(pr.ravel())
        return M.pixel_report(np.concatenate(gts), np.concatenate(prs))

    seg.pixel_threshold = max(((seg_pixels(va & (y == 1), t)["pixel_f1"] or 0), t) for t in (0.3, 0.4, 0.5, 0.6, 0.7))[1]
    seg_platt = Platt.fit(seg_score[va], y[va])
    seg.save(OUT / "mt_segnet" / VERSION / "model.pt")

    # defect-type classification on test defect images (dominant predicted region class)
    def type_eval(sel):
        yt, yp = [], []
        for i in np.flatnonzero(sel & (y == 1)):
            out = seg.predict(imgs[i])
            yt.append(samples[i].label)
            yp.append(max(out.regions, key=lambda r: r.area_px).defect_type if out.regions else "none")
        return M.multiclass_report(yt, yp, D.MT_CLASSES + ["none"])

    # ---------------- Classical baseline
    cl = ClassicalDetector()
    cl_score = np.array([cl.predict(im).image_score for im in imgs])

    # ---------------- Ensemble (stacked logistic fusion of the two learned detectors, fit on validation)
    F = np.stack([pc_score, seg_score], 1)
    mu, sd = F[va].mean(0), F[va].std(0) + 1e-9
    lr = LogisticRegression(C=10.0, class_weight="balanced", max_iter=2000).fit((F[va] - mu) / sd, y[va])
    coef = (lr.coef_[0] / sd).tolist()
    intercept = float(lr.intercept_[0] - (lr.coef_[0] * mu / sd).sum())
    p_ens = 1 / (1 + np.exp(-(F @ np.array(coef) + intercept)))
    # Operating point, declared before looking at test results: tolerate up to 2% of validation defects below the pass
    # threshold and 2% of validation goods above the reject threshold. The zero-tolerance point is reported alongside.
    TOL = 0.02
    t_low, t_high = select_review_band(p_ens[va], y[va], max_escape=TOL, max_false_reject=TOL)
    operating_points = []
    for tol in (0.0, 0.02, 0.05):
        lo, hi = select_review_band(p_ens[va], y[va], max_escape=tol, max_false_reject=tol)
        operating_points.append({"validation_tolerance": tol, "shipped": tol == TOL, "val": M.triage_report(y[va], p_ens[va], lo, hi),
                                 "test": M.triage_report(y[te], p_ens[te], lo, hi)})

    def image_metrics(p, sel, name):
        out = {"auroc": M.auroc(y[sel], p[sel]), **M.binary_report(y[sel], p[sel] >= 0.5), "calibration": M.ece(y[sel], p[sel])}
        log(f"  {name}: AUROC {out['auroc']} F1 {out['f1']} FPR {out['false_positive_rate']} FNR {out['false_negative_rate']} ECE {out['calibration']['ece']}")
        return out

    per_defect = {}
    for c in D.MT_CLASSES:
        sel = te & np.array([s.label == c for s in samples])
        n = int(sel.sum())
        det_k = int((p_ens[sel] >= 0.5).sum())
        not_passed = int((p_ens[sel] > t_low).sum())
        per_defect[c] = {"support": n, "detected_at_0.5": det_k, "recall_at_0.5": round(det_k / max(1, n), 4), "recall_ci95": M.wilson(det_k, n),
                         "not_auto_passed": not_passed, "caught_or_reviewed_rate": round(not_passed / max(1, n), 4)}

    res = {
        "patchcore": {"val": image_metrics(pc_platt(pc_score), va, "patchcore val"), "test": image_metrics(pc_platt(pc_score), te, "patchcore test"),
                      "test_pixel": pc_pixels(te & (y == 1), pc.pixel_threshold), "cross_validation": cv_res},
        "segnet": {"val": image_metrics(seg_platt(seg_score), va, "segnet val"), "test": image_metrics(seg_platt(seg_score), te, "segnet test"),
                   "test_pixel": seg_pixels(te & (y == 1), seg.pixel_threshold), "test_defect_type": type_eval(te)},
        "classical": {"test": {"auroc": M.auroc(y[te], cl_score[te]), **M.binary_report(y[te], cl_score[te] > 0)}},
        "ensemble": {"val": image_metrics(p_ens, va, "ensemble val"), "test": image_metrics(p_ens, te, "ensemble test"),
                     "test_triage": M.triage_report(y[te], p_ens[te], t_low, t_high), "val_triage": M.triage_report(y[va], p_ens[va], t_low, t_high),
                     "test_per_defect": per_defect, "operating_points": operating_points},
    }
    log("MT ensemble triage (test):", json.dumps(res["ensemble"]["test_triage"]))
    sc = split_counts(samples)
    common_lim = [
        "Validated only on the Magnetic Tile dataset (grayscale ferrite tile surfaces, one imaging setup).",
        f"Test split has {int((te & (y == 1)).sum())} defective and {int((te & (y == 0)).sum())} good images: far too few to verify a 99.9% target "
        "(see the confidence intervals).",
        "Images are resized to a fixed square input; very small defects (blowholes) lose resolution.",
    ]
    write_json(OUT / "mt_patchcore" / VERSION / "card.json", {
        "name": "mt_patchcore", "version": VERSION, "kind": "anomaly", "material": "ceramics",
        "architecture": "PatchCore: frozen ImageNet MobileNetV2 (blocks 6+13), 3x3 avg-pooled patch features, greedy k-center coreset (4000), 1-NN distance",
        "dataset": "Magnetic Tile Surface Defects", "splits": sc, "trained_on": "train split, defect-free images only",
        "calibration": pc_platt.to_dict(), "pixel_threshold": pc.pixel_threshold, "metrics": res["patchcore"], "limitations": common_lim, "created_at": now()})
    write_json(OUT / "mt_segnet" / VERSION / "card.json", {
        "name": "mt_segnet", "version": VERSION, "kind": "segmentation", "material": "ceramics", "classes": D.MT_CLASSES,
        "architecture": "MobileNetV2 encoder (ImageNet transfer) + FPN decoder, 320x320, CE + Dice", "dataset": "Magnetic Tile Surface Defects",
        "splits": sc, "training": tlog, "calibration": seg_platt.to_dict(), "pixel_threshold": seg.pixel_threshold, "metrics": res["segnet"],
        "limitations": common_lim, "created_at": now()})
    for key, model, task in [("patchcore", "mt_patchcore", "anomaly detection (image-level) + localization"),
                             ("segnet", "mt_segnet", "segmentation + defect classification"),
                             ("classical", "classical_cv", "training-free screening baseline"),
                             ("ensemble", "mt_ensemble", "ensemble decision (PatchCore + SegNet, stacked) with review band")]:
        record(evals, id=f"{model}-mt-test", model=model, version=VERSION if model != "classical_cv" else "1.0", material="ceramics",
               dataset="Magnetic Tile Surface Defects", split="test", task=task, n=int(te.sum()), metrics=res[key], notes=common_lim)
    write_json(OUT / "profiles" / "magnetic_tile.json", {
        "key": "magnetic_tile", "material": "ceramics", "name": "Ferrite magnetic tile surface", "product_category": "Sintered ferrite magnetic tile",
        "requires_reference": False, "mm_per_pixel": None,
        "detectors": [{"type": "patchcore", "model": "mt_patchcore", "version": VERSION, "calibration": pc_platt.to_dict()},
                      {"type": "segnet", "model": "mt_segnet", "version": VERSION, "calibration": seg_platt.to_dict()}],
        "decision": {"mode": "fusion", "features": ["mt_patchcore", "mt_segnet"], "coef": coef, "intercept": intercept, "t_low": t_low, "t_high": t_high,
                     "image_level_validated": True, "validated": True, "evidence": "mt_ensemble-mt-test"},
        "drift_reference": {"mt_patchcore": np.quantile(pc_score[va & (y == 0)], np.linspace(0, 1, 11)).round(4).tolist(),
                            "brightness": np.quantile([float(to_gray(imgs[i]).mean()) for i in np.flatnonzero(va)], np.linspace(0, 1, 11)).round(2).tolist()},
    })
    flush_evals("mt", evals)


# ============================================================================================ CFD
def tolerant_pixels(gts, prs, r=2):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    tp_p = pred = tp_g = gt = 0
    for g, p in zip(gts, prs):
        g, p = g.astype(np.uint8), p.astype(np.uint8)
        tp_p += int((p & cv2.dilate(g, k)).sum()); pred += int(p.sum())
        tp_g += int((g & cv2.dilate(p, k)).sum()); gt += int(g.sum())
    pr, rc = tp_p / max(1, pred), tp_g / max(1, gt)
    return {"tolerance_px": r, "pixel_precision": round(pr, 4), "pixel_recall": round(rc, 4), "pixel_f1": round(2 * pr * rc / max(1e-9, pr + rc), 4)}


def stage_cfd():
    evals: list = []
    samples = D.load_crackforest()
    imgs = [s.image() for s in samples]
    masks = [D.cfd_mask(s) for s in samples]
    split = np.array([s.split for s in samples])
    tr, va, te = (np.flatnonzero(split == k) for k in ("train", "val", "test"))
    log(f"CFD: train {len(tr)} val {len(va)} test {len(te)}")
    seg = SegDetector(["crack"], input_size=(320, 480), name="concrete_crack_segnet", version=VERSION)
    tlog = train_segnet(seg, [imgs[i] for i in tr], [masks[i] for i in tr], epochs=60, batch=8, balance_empty=False, log=log)

    def run(idx, thr):
        gts, prs = [], []
        for i in idx:
            p = seg.prob_maps([imgs[i]])[0]
            prs.append(cv2.resize((1 - p[0]).astype(np.float32), (masks[i].shape[1], masks[i].shape[0])) > thr)
            gts.append(masks[i] > 0)
        return gts, prs

    best = max((M.pixel_report(np.concatenate([g.ravel() for g in gs]), np.concatenate([p.ravel() for p in ps]))["pixel_f1"] or 0, t)
               for t in (0.2, 0.3, 0.4, 0.5, 0.6) for gs, ps in [run(va, t)])
    seg.pixel_threshold = best[1]
    gts, prs = run(te, seg.pixel_threshold)
    strict = M.pixel_report(np.concatenate([g.ravel() for g in gts]), np.concatenate([p.ravel() for p in prs]))
    tol = tolerant_pixels(gts, prs, 2)
    cl = ClassicalDetector()
    cprs = []
    for i in te:
        out = cl.predict(imgs[i])
        m = np.zeros(masks[i].shape, bool)
        for r in out.regions:
            m |= r.mask
        cprs.append(m)
    cl_strict = M.pixel_report(np.concatenate([g.ravel() for g in gts]), np.concatenate([p.ravel() for p in cprs]))
    cl_tol = tolerant_pixels(gts, cprs, 2)
    log("CFD test segnet:", strict, tol, "| classical:", cl_strict, cl_tol)
    seg.save(OUT / "concrete_crack_segnet" / VERSION / "model.pt")
    lim = [
        "CrackForest has 118 images (urban road surface, one phone camera); the test split is only %d images." % len(te),
        "Every image contains cracks, so image-level false-positive rate / AUROC cannot be measured; automatic PASS is disabled by default.",
        "Ground-truth cracks are 1-3 px wide, so strict pixel metrics are sensitive to 1 px offsets (2 px tolerant metrics also reported).",
    ]
    metrics = {"test_pixel_strict": strict, "test_pixel_tolerant": tol, "val_best_f1": best[0], "pixel_threshold": seg.pixel_threshold,
               "classical_baseline": {"test_pixel_strict": cl_strict, "test_pixel_tolerant": cl_tol}}
    write_json(OUT / "concrete_crack_segnet" / VERSION / "card.json", {
        "name": "concrete_crack_segnet", "version": VERSION, "kind": "segmentation", "material": "construction", "classes": ["crack"],
        "architecture": "MobileNetV2 encoder (ImageNet transfer) + FPN decoder, 320x480, CE + Dice", "dataset": "CrackForest (CFD)",
        "splits": {"train": len(tr), "val": len(va), "test": len(te)}, "training": tlog, "pixel_threshold": seg.pixel_threshold,
        "metrics": metrics, "limitations": lim, "created_at": now()})
    record(evals, id="concrete_crack_segnet-cfd-test", model="concrete_crack_segnet", version=VERSION, material="construction", dataset="CrackForest",
           split="test", task="crack segmentation", n=len(te), metrics=metrics, notes=lim)
    write_json(OUT / "profiles" / "pavement_crack.json", {
        "key": "pavement_crack", "material": "construction", "name": "Pavement / concrete surface cracks", "product_category": "Asphalt or concrete surface",
        "requires_reference": False, "mm_per_pixel": None,
        "detectors": [{"type": "segnet", "model": "concrete_crack_segnet", "version": VERSION}],
        "decision": {"mode": "regions", "region_confident": 0.8, "image_level_validated": False, "validated": True,
                     "evidence": "concrete_crack_segnet-cfd-test"},
    })
    flush_evals("cfd", evals)


# ======================================================================================= material
def stage_material():
    """Prototype (nearest-centroid) material suggestion over frozen backbone features."""
    evals: list = []
    sets = {"magnetic_tile": D.load_magnetic_tile(), "pcb_bare_board": D.load_deeppcb(), "pavement_crack": D.load_crackforest()}  # keyed by inspection profile
    pc = PatchCore()
    feats, labels, splits = [], [], []
    rng = np.random.default_rng(0)
    for mat, samples in sets.items():
        idx = rng.permutation(len(samples))[:400]
        ims = [samples[i].image() for i in idx]
        e = pc.embed_many(ims).mean((1, 2)).numpy()
        feats.append(e), labels.extend([mat] * len(idx)), splits.extend(["test" if samples[i].split == "test" else "train" for i in idx])
    X, yl, sp = np.concatenate(feats), np.array(labels), np.array(splits)
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    mats = list(sets)
    cents = np.stack([X[(yl == m) & (sp == "train")].mean(0) for m in mats])
    radius = [float(np.quantile(np.linalg.norm(X[(yl == m) & (sp == "train")] - cents[i], axis=1), 0.90)) for i, m in enumerate(mats)]  # tight on purpose: asking the operator is cheap
    d = np.linalg.norm(X[sp == "test"][:, None] - cents[None], axis=2)
    pred = np.array(mats)[d.argmin(1)]
    rep = M.multiclass_report(yl[sp == "test"], pred, mats)
    rejected = float((d.min(1) > np.array(radius)[d.argmin(1)]).mean())
    log("material id test:", rep["accuracy"], "rejected-as-unknown:", rejected)
    torch.save({"materials": mats, "centroids": torch.from_numpy(cents), "radius": radius}, OUT / "material_id" / VERSION / "model.pt") if (OUT / "material_id" / VERSION).mkdir(parents=True, exist_ok=True) is None else None
    lim = ["Knows only the three materials/imaging setups it has prototypes for; these datasets are visually trivial to tell apart, "
           "so this accuracy says nothing about distinguishing e.g. steel from aluminium.",
           "Anything farther from a prototype than 90% of that profile's own training images is reported as 'unknown' and the operator is asked "
           "to choose (so roughly 1 in 10 genuine images is also asked). Rejection of truly foreign materials was not benchmarked.",
           "It is a suggestion only: the operator's selection always overrides it."]
    metrics = {"test": rep, "test_rejected_as_unknown_rate": round(rejected, 4)}
    write_json(OUT / "material_id" / VERSION / "card.json", {
        "name": "material_id", "version": VERSION, "kind": "material_identification", "architecture": "nearest-centroid over mean MobileNetV2 patch features",
        "materials": mats, "dataset": "MT + DeepPCB + CrackForest (<=400 images each)", "metrics": metrics, "limitations": lim, "created_at": now()})
    record(evals, id="material_id-test", model="material_id", version=VERSION, material="(all)", dataset="MT + DeepPCB + CrackForest", split="test",
           task="material suggestion", n=rep["n"], metrics=metrics, notes=lim)
    flush_evals("material", evals)


if __name__ == "__main__":
    stages = sys.argv[1:] or ["pcb", "material", "cfd", "mt"]
    for st in stages:
        log(f"===== stage {st} =====")
        {"pcb": stage_pcb, "mt": stage_mt, "cfd": stage_cfd, "material": stage_material}[st]()
    log("done")
