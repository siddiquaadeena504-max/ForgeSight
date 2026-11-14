"""Fine-tuning routines (transfer learning from ImageNet features). CPU-capable; use GPU if present."""
from __future__ import annotations

import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from .backbones import IMAGENET_MEAN, IMAGENET_STD, get_device
from .detectors.refdiff import CropNet
from .detectors.segnet import SegDetector


def _prep(img: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img = cv2.resize(img, (size[1], size[0]), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def train_segnet(det: SegDetector, images: list[np.ndarray], masks: list[np.ndarray], epochs: int = 30, batch: int = 12,
                 lr: float = 1e-3, seed: int = 0, balance_empty: bool = True, log=print) -> dict:
    """masks: int arrays, 0 = background, k = class k (1-based). Returns a training log."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    dev = get_device()
    size = det.input_size
    X = np.stack([_prep(i, size) for i in images])
    Y = np.stack([cv2.resize(m.astype(np.uint8), (size[1], size[0]), interpolation=cv2.INTER_NEAREST) for m in masks])
    pos = np.array([y.any() for y in Y])
    mean = torch.tensor(IMAGENET_MEAN, device=dev).view(1, 3, 1, 1)
    std = torch.tensor(IMAGENET_STD, device=dev).view(1, 3, 1, 1)
    net = det.net
    opt = torch.optim.AdamW([{"params": net.encoder.parameters(), "lr": lr * 0.3},
                             {"params": [p for n, p in net.named_parameters() if not n.startswith("encoder.")], "lr": lr}], weight_decay=1e-4)
    # Class-balanced cross-entropy: without it, classes with large defects (break, uneven) swamp small ones (blowhole, crack)
    # and the per-pixel class head collapses onto them. Weight = (median defect-pixel count / class pixel count)^0.75, clipped.
    counts = np.bincount(Y.ravel(), minlength=len(det.classes) + 1).astype(np.float64)
    med = np.median(counts[1:][counts[1:] > 0]) if (counts[1:] > 0).any() else 1.0
    w = np.ones(len(det.classes) + 1, dtype=np.float32)
    w[1:] = np.clip((med / np.maximum(counts[1:], 1.0)) ** 0.75, 0.5, 30.0)
    ce_weight = torch.tensor(w, device=dev)
    pos_idx, neg_idx = np.flatnonzero(pos), np.flatnonzero(~pos)
    n_neg = min(len(neg_idx), len(pos_idx)) if balance_empty else len(neg_idx)
    steps = epochs * int(np.ceil((len(pos_idx) + n_neg) / batch))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[lr * 0.3, lr], total_steps=steps, pct_start=0.1)
    history, t0 = [], time.time()
    for ep in range(epochs):
        net.train()
        idx = np.concatenate([pos_idx, rng.choice(neg_idx, n_neg, replace=False)]) if n_neg else pos_idx.copy()
        rng.shuffle(idx)
        tot, nb = 0.0, 0
        for i in range(0, len(idx), batch):
            b = idx[i : i + batch]
            x = torch.from_numpy(X[b]).to(dev).permute(0, 3, 1, 2).float() / 255.0
            y = torch.from_numpy(Y[b]).to(dev).long()
            if rng.random() < 0.5:
                x, y = x.flip(3), y.flip(2)
            if rng.random() < 0.5:
                x, y = x.flip(2), y.flip(1)
            x = (x * (0.8 + 0.4 * torch.rand(len(b), 1, 1, 1, device=dev)) + 0.1 * (torch.rand(len(b), 1, 1, 1, device=dev) - 0.5)).clamp(0, 1)
            logits = net((x - mean) / std)
            ce = F.cross_entropy(logits, y, weight=ce_weight)
            p_def = 1 - torch.softmax(logits, 1)[:, 0]
            t = (y > 0).float()
            dice = 1 - (2 * (p_def * t).sum((1, 2)) + 1) / (p_def.sum((1, 2)) + t.sum((1, 2)) + 1)
            loss = ce + dice.mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot, nb = tot + float(loss.detach()), nb + 1
        history.append(round(tot / nb, 4))
        log(f"  [segnet {det.name}] epoch {ep + 1}/{epochs} loss {tot / nb:.4f} ({time.time() - t0:.0f}s)")
    net.eval()
    return {"epochs": epochs, "loss_history": history, "train_images": int(len(X)), "train_seconds": round(time.time() - t0, 1),
            "optimizer": "AdamW+OneCycle", "lr": lr, "batch": batch, "augmentation": "flips, brightness/contrast jitter",
            "class_weights": {c: round(float(v), 2) for c, v in zip(det.classes, w[1:])}}


def train_cropnet(num_classes: int, X: np.ndarray, y: np.ndarray, epochs: int = 12, batch: int = 64, lr: float = 2e-3, seed: int = 0, log=print):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    dev = get_device()
    net = CropNet(num_classes).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    steps = epochs * int(np.ceil(len(X) / batch))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.15)
    counts = np.bincount(y, minlength=num_classes).astype(np.float32)
    w = torch.tensor((counts.sum() / np.maximum(counts, 1) / num_classes) ** 0.5, device=dev)
    history, t0 = [], time.time()
    for ep in range(epochs):
        net.train()
        idx = rng.permutation(len(X))
        tot, nb = 0.0, 0
        for i in range(0, len(idx), batch):
            b = idx[i : i + batch]
            x = torch.from_numpy(X[b]).to(dev)
            t = torch.from_numpy(y[b]).to(dev).long()
            if rng.random() < 0.5:
                x = x.flip(3)
            if rng.random() < 0.5:
                x = x.flip(2)
            if rng.random() < 0.5:
                x = x.transpose(2, 3)
            loss = F.cross_entropy(net(x), t, weight=w)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot, nb = tot + float(loss.detach()), nb + 1
        history.append(round(tot / nb, 4))
        log(f"  [cropnet] epoch {ep + 1}/{epochs} loss {tot / nb:.4f} ({time.time() - t0:.0f}s)")
    net.eval()
    return net, {"epochs": epochs, "loss_history": history, "train_crops": int(len(X)), "train_seconds": round(time.time() - t0, 1)}
