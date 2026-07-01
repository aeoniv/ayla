"""MediaPipe pose extraction + sequence comparison.

cv2 and mediapipe are heavy native deps; they're lazy-imported inside
`extract_landmarks` so the rest of the service (and unit tests of the scoring
math) import without them. The Docker image installs both.

Landmark schema: MediaPipe Pose, 33 landmarks, each (x, y, z, visibility),
image-normalized coordinates in [0, 1].
"""
from __future__ import annotations

import numpy as np

LANDMARK_SCHEMA = "mediapipe_pose_33"
NUM_LANDMARKS = 33

# Landmark index groups for per-region deviation reporting.
REGIONS = {
    "head": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "left_arm": [11, 13, 15, 17, 19, 21],
    "right_arm": [12, 14, 16, 18, 20, 22],
    "torso": [11, 12, 23, 24],
    "left_leg": [23, 25, 27, 29, 31],
    "right_leg": [24, 26, 28, 30, 32],
}

_L_SHOULDER, _R_SHOULDER, _L_HIP, _R_HIP = 11, 12, 23, 24


def extract_landmarks(video_path: str) -> dict:
    """Run MediaPipe Pose over a video file. Returns {fps, frame_count, frames}.

    `frames` is a list of 33x4 lists (x, y, z, visibility). Frames with no
    detected pose are skipped.
    """
    import cv2  # lazy
    import mediapipe as mp  # lazy

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames: list[list[list[float]]] = []

    with mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1) as pose:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = pose.process(rgb)
            if not res.pose_landmarks:
                continue
            frames.append(
                [[lm.x, lm.y, lm.z, lm.visibility] for lm in res.pose_landmarks.landmark]
            )
    cap.release()
    return {"fps": fps, "frame_count": len(frames), "frames": frames}


# --- scoring math (pure numpy, unit-testable without cv2/mediapipe) --------

def _to_array(frames: list) -> np.ndarray:
    """(F, 33, 4) float array; use only x,y,z for geometry."""
    return np.asarray(frames, dtype=np.float64)


def _normalize_frame(xyz: np.ndarray) -> np.ndarray:
    """Translate to hip-center origin and scale by torso length.

    Makes the comparison invariant to where the person is in-frame and their
    apparent size. xyz: (33, 3).
    """
    hip_center = (xyz[_L_HIP] + xyz[_R_HIP]) / 2.0
    shoulder_center = (xyz[_L_SHOULDER] + xyz[_R_SHOULDER]) / 2.0
    torso = np.linalg.norm(shoulder_center - hip_center)
    scale = torso if torso > 1e-6 else 1.0
    return (xyz - hip_center) / scale


def _resample(seq: np.ndarray, n: int) -> np.ndarray:
    """Linearly resample a (F, 33, 3) sequence to (n, 33, 3) over normalized time."""
    f = seq.shape[0]
    if f == n:
        return seq
    src = np.linspace(0.0, 1.0, f)
    dst = np.linspace(0.0, 1.0, n)
    out = np.empty((n, seq.shape[1], seq.shape[2]))
    for j in range(seq.shape[1]):
        for k in range(seq.shape[2]):
            out[:, j, k] = np.interp(dst, src, seq[:, j, k])
    return out


def _prepare(frames: list, n: int) -> np.ndarray:
    arr = _to_array(frames)[:, :, :3]  # drop visibility
    norm = np.stack([_normalize_frame(arr[i]) for i in range(arr.shape[0])])
    return _resample(norm, n)


def compare(reference: dict, attempt: dict, n: int = 64) -> dict:
    """Compare two extracted sequences.

    Returns {score: 0-100, worst_region, region_scores}. Higher score = closer.
    """
    if not reference.get("frames") or not attempt.get("frames"):
        raise ValueError("empty landmark sequence")

    ref = _prepare(reference["frames"], n)      # (n, 33, 3)
    att = _prepare(attempt["frames"], n)

    # per-landmark, per-frame euclidean distance -> (n, 33)
    dist = np.linalg.norm(ref - att, axis=2)

    region_scores: dict[str, float] = {}
    region_mean_dist: dict[str, float] = {}
    for name, idxs in REGIONS.items():
        md = float(dist[:, idxs].mean())
        region_mean_dist[name] = md
        # map mean distance (in torso-length units) to 0-100; ~0.5 torso => ~0
        region_scores[name] = round(max(0.0, 100.0 * (1.0 - md / 0.5)), 1)

    worst_region = max(region_mean_dist, key=region_mean_dist.get)
    overall = float(dist.mean())
    score = round(max(0.0, min(100.0, 100.0 * (1.0 - overall / 0.5))), 1)

    return {"score": score, "worst_region": worst_region, "region_scores": region_scores}
