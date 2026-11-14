"""Feature-extraction backbones.

The default backbone is an ImageNet-pretrained MobileNetV2. The network definition below follows
https://github.com/d-li14/mobilenetv2.pytorch (Apache-2.0) so that its published checkpoint
(`mobilenetv2-c5e733a8.pth`) loads without key remapping.

Other backbones (ResNet / Wide-ResNet / ViT via timm) plug in through `load_backbone("timm:<name>")`.
They require their pretrained weights to be reachable or cached locally; nothing is silently
substituted - if weights are missing the loader raises.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import torch
import torch.nn as nn

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def get_device() -> torch.device:
    forced = os.environ.get("FS_DEVICE")
    if forced:
        return torch.device(forced)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def weights_dir() -> Path:
    return Path(os.environ.get("FS_WEIGHTS_DIR", Path(__file__).resolve().parents[3] / "data" / "weights"))


def _conv_3x3_bn(inp, oup, stride):
    return nn.Sequential(nn.Conv2d(inp, oup, 3, stride, 1, bias=False), nn.BatchNorm2d(oup), nn.ReLU6(inplace=True))


def _conv_1x1_bn(inp, oup):
    return nn.Sequential(nn.Conv2d(inp, oup, 1, 1, 0, bias=False), nn.BatchNorm2d(oup), nn.ReLU6(inplace=True))


class InvertedResidual(nn.Module):
    def __init__(self, inp, oup, stride, expand_ratio):
        super().__init__()
        hidden = round(inp * expand_ratio)
        self.identity = stride == 1 and inp == oup
        if expand_ratio == 1:
            self.conv = nn.Sequential(
                nn.Conv2d(hidden, hidden, 3, stride, 1, groups=hidden, bias=False), nn.BatchNorm2d(hidden), nn.ReLU6(inplace=True),
                nn.Conv2d(hidden, oup, 1, 1, 0, bias=False), nn.BatchNorm2d(oup),
            )
        else:
            self.conv = nn.Sequential(
                nn.Conv2d(inp, hidden, 1, 1, 0, bias=False), nn.BatchNorm2d(hidden), nn.ReLU6(inplace=True),
                nn.Conv2d(hidden, hidden, 3, stride, 1, groups=hidden, bias=False), nn.BatchNorm2d(hidden), nn.ReLU6(inplace=True),
                nn.Conv2d(hidden, oup, 1, 1, 0, bias=False), nn.BatchNorm2d(oup),
            )

    def forward(self, x):
        return x + self.conv(x) if self.identity else self.conv(x)


class MobileNetV2(nn.Module):
    CFGS = [[1, 16, 1, 1], [6, 24, 2, 2], [6, 32, 3, 2], [6, 64, 4, 2], [6, 96, 3, 1], [6, 160, 3, 2], [6, 320, 1, 1]]
    # index of the last block at each stride -> (channels, stride)
    TAPS = {3: (24, 4), 6: (32, 8), 13: (96, 16), 17: (320, 32)}

    def __init__(self, num_classes: int = 1000):
        super().__init__()
        inp = 32
        layers = [_conv_3x3_bn(3, inp, 2)]
        for t, c, n, s in self.CFGS:
            for i in range(n):
                layers.append(InvertedResidual(inp, c, s if i == 0 else 1, t))
                inp = c
        self.features = nn.Sequential(*layers)
        self.conv = _conv_1x1_bn(inp, 1280)
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.classifier = nn.Linear(1280, num_classes)

    def forward_taps(self, x: torch.Tensor, taps: tuple[int, ...]) -> list[torch.Tensor]:
        out = []
        last = max(taps)
        for i, layer in enumerate(self.features):
            x = layer(x)
            if i in taps:
                out.append(x)
            if i == last:
                break
        return out

    def forward(self, x):
        x = self.avgpool(self.conv(self.features(x))).flatten(1)
        return self.classifier(x)


def mobilenetv2_imagenet(pretrained: bool = True) -> MobileNetV2:
    model = MobileNetV2()
    if pretrained:
        path = weights_dir() / "mobilenetv2-c5e733a8.pth"
        if not path.exists():
            raise FileNotFoundError(
                f"Pretrained MobileNetV2 weights not found at {path}. Run scripts/fetch_assets.sh or set FS_WEIGHTS_DIR."
            )
        state = torch.load(path, map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
    return model


class TapBackbone(nn.Module):
    """Uniform interface: forward(x) -> list of feature maps."""

    def __init__(self, name: str, taps: tuple[int, ...] = (6, 13)):
        super().__init__()
        self.name = name
        if name == "mobilenetv2":
            self.net = mobilenetv2_imagenet(True)
            self.taps = taps
            self.kind = "mnv2"
            self.channels = [MobileNetV2.TAPS[t][0] for t in taps]
        elif name.startswith("timm:"):
            import timm  # optional; needs reachable/cached pretrained weights

            self.net = timm.create_model(name.split(":", 1)[1], pretrained=True, features_only=True)
            self.kind = "timm"
            self.channels = list(self.net.feature_info.channels())
        else:
            raise ValueError(f"Unknown backbone '{name}'")
        self.eval()
        for p in self.parameters():
            p.requires_grad_(False)

    @torch.no_grad()
    def forward(self, x):
        if self.kind == "mnv2":
            return self.net.forward_taps(x, self.taps)
        return list(self.net(x))


@lru_cache(maxsize=4)
def load_backbone(name: str = "mobilenetv2", taps: tuple[int, ...] = (6, 13)) -> TapBackbone:
    return TapBackbone(name, taps).to(get_device())


def preprocess_batch(images_bgr: list, size: tuple[int, int]) -> torch.Tensor:
    """BGR/gray uint8 arrays -> normalized float tensor [N,3,H,W] (size = (H, W))."""
    import cv2
    import numpy as np

    batch = []
    for img in images_bgr:
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        img = cv2.resize(img, (size[1], size[0]), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        rgb = (rgb - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(IMAGENET_STD, dtype=np.float32)
        batch.append(rgb.transpose(2, 0, 1))
    return torch.from_numpy(np.stack(batch)).to(get_device())
