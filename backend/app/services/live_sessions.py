"""Reference-learning sessions for live / video inspection of materials that have no trained model.

The operator marks a short stretch of defect-free footage; a PatchCore memory bank is fitted on those frames
(in memory, per session) and later frames are flagged where they deviate from it. This is an *unvalidated*
detector by construction: it localizes deviations for a human, it never passes or rejects a part on its own.
"""
from __future__ import annotations

import threading
import time
import uuid

import numpy as np

from ..ml.detectors.patchcore import PatchCore

TTL_SECONDS = 3 * 3600
MAX_SESSIONS = 24
K_SIGMA = {"low": 4.5, "normal": 3.0, "high": 2.0}  # robust sigmas above the typical peak of a normal frame
_sessions: dict[str, tuple[PatchCore, float, dict]] = {}
_lock = threading.Lock()


def _input_size(h: int, w: int, long_side: int = 448) -> tuple[int, int]:
    f = long_side / max(h, w)
    return max(96, int(round(h * f / 32)) * 32), max(96, int(round(w * f / 32)) * 32)


def create(frames: list[np.ndarray]) -> tuple[str, dict]:
    if len(frames) < 6:
        raise ValueError("At least 6 defect-free reference frames are needed")
    h, w = frames[0].shape[:2]
    sid = uuid.uuid4().hex
    pc = PatchCore(input_size=_input_size(h, w), name="learned_reference", version=f"session-{sid[:8]}")
    emb = pc.embed_many(frames)
    # Threshold from held-out reference frames (two-fold): how anomalous does a *normal* frame look against the other
    # normal frames? Peaks are measured on the same smoothed full-resolution map that predict() thresholds, and the
    # threshold is a robust upper bound (median + k * MAD) so that one odd reference frame does not dictate it.
    idx = np.arange(len(frames))
    peaks = []
    for fold in (0, 1):
        pc.fit_embeddings(emb[idx % 2 != fold], coreset=8000, seed=fold, method="random")  # fast: only used to set the threshold
        peaks += [float(pc.full_map(d, h, w).max()) for d in pc.distance_maps(emb[idx % 2 == fold])]
    pc.fit_embeddings(emb, coreset=3000, presample=20000)
    med = float(np.median(peaks))
    mad = max(float(np.median(np.abs(np.array(peaks) - med)) * 1.4826), 0.02 * med)
    pc.pixel_threshold = med + K_SIGMA["normal"] * mad
    pc.score_scale = 1.6 * pc.pixel_threshold
    info = {"session_id": sid, "reference_frames": len(frames), "input_size": list(pc.input_size), "pixel_threshold": round(pc.pixel_threshold, 4), "peak_median": med, "peak_mad": mad,
            "note": "Deviations from the learned reference are candidates for human review; this detector is not validated."}
    with _lock:
        now = time.time()
        for k in [k for k, (_, t, _) in _sessions.items() if now - t > TTL_SECONDS]:
            _sessions.pop(k, None)
        while len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(min(_sessions, key=lambda k: _sessions[k][1]))
        _sessions[sid] = (pc, now, info)
    return sid, info


def get(sid: str) -> PatchCore | None:
    with _lock:
        item = _sessions.get(sid)
        return item[0] if item else None


def profile_for(sid: str, sensitivity: str = "normal") -> dict:
    with _lock:
        info = _sessions[sid][2]
    med, mad = info["peak_median"], info["peak_mad"]
    scale = (med + K_SIGMA.get(sensitivity, 3.0) * mad) / (med + K_SIGMA["normal"] * mad)
    return {"threshold_scale": scale, "key": None, "name": "Learned from reference footage (unvalidated)", "requires_reference": False,
            "detectors": [{"type": "session", "id": sid}], "decision": {"mode": "screening", "validated": False, "image_level_validated": False}}
