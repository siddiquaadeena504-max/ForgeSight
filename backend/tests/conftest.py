import os
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="fs-test-"))
REAL_MODELS = Path(__file__).resolve().parents[2] / "data" / "models"
(_TMP / "models").mkdir()
for sub in ("pcb_refdiff", "material_id", "profiles", "evaluations", "mt_patchcore", "mt_segnet", "concrete_crack_segnet"):
    if (REAL_MODELS / sub).exists():
        os.symlink(REAL_MODELS / sub, _TMP / "models" / sub)
os.environ.update({
    "FS_DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}", "FS_STORAGE_DIR": str(_TMP / "storage"), "FS_MODELS_DIR": str(_TMP / "models"),
    "FS_JOBS_SYNC": "1", "FS_SECRET_KEY": "test-secret-key-test-secret-key-0000", "FS_ADMIN_PASSWORD": "AdminPass!2026",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

EXTERNAL = Path(__file__).resolve().parents[2] / "data" / "external"


def texture(seed: int, size: int = 256, defect: str | None = None) -> np.ndarray:
    """Synthetic brushed-surface texture, optionally with a clearly visible defect. Test fixture only."""
    rng = np.random.default_rng(seed)
    base = rng.normal(128, 6, (size, size)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 1.2) + np.linspace(-4, 4, size)[None, :]
    base += cv2.GaussianBlur(rng.normal(0, 14, (size, size)).astype(np.float32), (1, 31), 0)
    img = np.clip(base, 0, 255).astype(np.uint8)
    if defect == "blob":
        cx, cy = rng.integers(60, size - 60, 2)
        cv2.circle(img, (int(cx), int(cy)), 14, 30, -1)
    elif defect == "scratch":
        x0, y0 = rng.integers(30, size // 2, 2)
        cv2.line(img, (int(x0), int(y0)), (int(x0) + 110, int(y0) + 70), 235, 3)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def jpg(img: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def png(img: np.ndarray) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    shutil.rmtree(_TMP, ignore_errors=True)


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin@forgesight.local", "AdminPass!2026")


@pytest.fixture(scope="session")
def users(client, admin):
    out = {"admin": admin}
    for role in ("viewer", "inspector", "engineer"):
        r = client.post("/api/users", headers=admin, json={"email": f"{role}@test.local", "full_name": role, "password": "Password!2026", "role": role})
        assert r.status_code == 201, r.text
        out[role] = _login(client, f"{role}@test.local", "Password!2026")
    return out


needs_pcb = pytest.mark.skipif(not (REAL_MODELS / "pcb_refdiff").exists() or not (EXTERNAL / "DeepPCB").exists(), reason="PCB model/dataset not present")
needs_mt = pytest.mark.skipif(not (REAL_MODELS / "profiles" / "magnetic_tile.json").exists() or not (EXTERNAL / "Magnetic-tile-defect-datasets").exists(),
                              reason="magnetic tile models/dataset not present")
