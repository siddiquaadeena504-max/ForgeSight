"""Process-wide engine singletons."""
from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from ..ml.pipeline import InspectionEngine, ModelRegistry


@lru_cache
def get_registry() -> ModelRegistry:
    return ModelRegistry(get_settings().models_dir)


@lru_cache
def get_engine() -> InspectionEngine:
    return InspectionEngine(get_registry())


@lru_cache
def get_material_identifier():
    """None when no identifier model is installed: the UI then always asks for the material."""
    from ..ml.material_id import MaterialIdentifier

    base = get_settings().models_dir / "material_id"
    versions = sorted(p.name for p in base.glob("*") if (p / "model.pt").exists()) if base.exists() else []
    return MaterialIdentifier(base / versions[-1] / "model.pt") if versions else None


def system_info() -> dict:
    import cv2
    import torch

    from ..ml.backbones import get_device

    dev = get_device()
    info = {"device": str(dev), "torch": torch.__version__, "opencv": cv2.__version__, "cuda_available": torch.cuda.is_available(),
            "cpu_threads": torch.get_num_threads(), "gpu": None}
    if torch.cuda.is_available():
        info["gpu"] = {"name": torch.cuda.get_device_name(0), "memory_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)}
    return info
