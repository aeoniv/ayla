"""MediaPipe pose extraction + sequence comparison.

cv2 and mediapipe are heavy native deps; they're lazy-imported inside
`extract_landmarks` so the rest of the service (and unit tests of the scoring
math) import without them. The Docker image installs both.

Landmark schema: MediaPipe Pose, 33 landmarks, each (x, y, z, visibility),
image-normalized coordinates in [0, 1]. Both the stored reference and the live
student pose come from the SAME MediaPipe model, so the 33-landmark ordering is
shared — `_as_landmarks` enforces that shape before any geometry runs, because a
mismatched ordering makes every distance meaningless.
"""
from __future__ import annotations

import numpy as np

LANDMARK_SCHEMA = "mediapipe_pose_33"
NUM_LANDMARKS = 33

# We compare in the image plane (x, y) only. MediaPipe's z is a rough,
# single-camera depth estimate — noisy, and it IS the camera-distance axis, so
# including it re-introduces the very false negatives normalization removes.
FEATURE_DIMS = 2

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

# Named difficulty gates (0-100 score thresholds). The client also sends a
# continuous slider value which, when present, OVERRIDES these — but the named
# levels are the canonical anchors and the server-side fallback.
DIFFICULTY: dict[str, float] = {
    "easy": 55.0,
    "medium": 70.0,
    "hard": 85.0,
}
DEFAULT_DIFFICULTY = "medium"

# Fraction of its score a pose keeps when it fails the difficulty gate. Missing
# the gate has to cost real points, otherwise "almost right on hard" would
# aggregate like a clean hit.
FAIL_PENALTY = 0.35

# Threshold override is clamped to this sane band regardless of what the client
# sends.
_MIN_THRESHOLD, _MAX_THRESHOLD = 30.0, 95.0


# --- extraction (needs cv2 + mediapipe) ------------------------------------

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
    timestamps: list[float] = []

    with mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1) as pose:
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = (cap.get(cv2.CAP_PROP_POS_MSEC) or (idx / fps * 1000.0)) / 1000.0
            idx += 1
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = pose.process(rgb)
            if not res.pose_landmarks:
                continue
            frames.append(
                [[lm.x, lm.y, lm.z, lm.visibility] for lm in res.pose_landmarks.landmark]
            )
            timestamps.append(t)
    cap.release()
    return {"fps": fps, "frame_count": len(frames), "frames": frames, "timestamps": timestamps}


def build_checkpoints(seq: dict, marked_seconds: list[float]) -> list[dict]:
    """Pick the extracted pose nearest each admin-marked timestamp.

    Returns an ordered checkpoint list [{index, timestamp_seconds, landmarks}].
    """
    ts = seq.get("timestamps") or []
    frames = seq["frames"]
    if not ts:
        raise ValueError("sequence has no timestamps")
    out: list[dict] = []
    used_frames: set[int] = set()
    for i, t in enumerate(sorted(marked_seconds)):
        j = min(range(len(ts)), key=lambda k: abs(ts[k] - t))
        # Two marks resolving to the same detected frame would silently store a
        # duplicate checkpoint — the marks are too close together; reject loudly.
        if j in used_frames:
            raise ValueError(
                f"checkpoint at {t:.2f}s resolves to the same frame as an earlier "
                f"mark — space checkpoints further apart"
            )
        used_frames.add(j)
        # Store the ACTUAL timestamp of the frame the landmarks came from, not
        # the owner's marked time. The client pauses the avatar video at this
        # timestamp, so the displayed frame and the ghost skeleton must be the
        # same frame — otherwise the pose drifts (worst on fast parts like hands)
        # because MediaPipe skips undetected frames and ts[j] != t.
        out.append(
            {"index": i, "timestamp_seconds": float(ts[j]),
             "marked_seconds": float(t), "landmarks": frames[j]}
        )
    return out


# --- coordinate mapping guard (concern #3) ---------------------------------

def _as_landmarks(frame, name: str = "pose") -> np.ndarray:
    """Coerce one pose to a validated (33, >=3) float array.

    Both sides are MediaPipe-33, so the ordering already lines up — but a
    truncated/ragged/mis-shaped payload would silently pair the wrong joints and
    produce a garbage score. Reject it loudly instead.
    """
    arr = np.asarray(frame, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] != NUM_LANDMARKS or arr.shape[1] < 3:
        raise ValueError(
            f"{name} must be {NUM_LANDMARKS} MediaPipe landmarks of >=3 values, "
            f"got shape {arr.shape}"
        )
    return arr


def _as_sequence(frames) -> np.ndarray:
    """Coerce a list of poses to a validated (F, 33, >=3) float array."""
    arr = np.asarray(frames, dtype=np.float64)
    if arr.ndim != 3 or arr.shape[1] != NUM_LANDMARKS or arr.shape[2] < 3:
        raise ValueError(
            f"sequence must be Fx{NUM_LANDMARKS}x>=3 landmarks, got shape {arr.shape}"
        )
    return arr


# --- normalization (concern #1) --------------------------------------------

def _norm_points(arr: np.ndarray) -> np.ndarray:
    """Translate a pose to hip-center origin and scale to a canonical body size.

    Returns (33, 2) image-plane points. Scale is the torso length (shoulder
    center -> hip center); if the torso collapses (side-on frame / bad
    detection) it falls back to shoulder width, then 1.0. After this the same
    pose performed near or far from the camera maps to the same coordinates, so
    comparison measures the SHAPE of the pose, not the dancer's distance.
    """
    xy = arr[:, :FEATURE_DIMS]
    hip = (xy[_L_HIP] + xy[_R_HIP]) / 2.0
    shoulder = (xy[_L_SHOULDER] + xy[_R_SHOULDER]) / 2.0
    torso = float(np.linalg.norm(shoulder - hip))
    if torso <= 1e-6:
        torso = float(np.linalg.norm(xy[_L_SHOULDER] - xy[_R_SHOULDER]))
    scale = torso if torso > 1e-6 else 1.0
    return (xy - hip) / scale


def _visibility(arr: np.ndarray) -> np.ndarray:
    """Per-landmark visibility in [0, 1]; all-ones when absent."""
    if arr.shape[1] >= 4:
        return np.clip(arr[:, 3], 0.0, 1.0)
    return np.ones(arr.shape[0])


def _weighted_mean(dist: np.ndarray, weights: np.ndarray) -> float:
    """Visibility-weighted mean distance.

    Joints the camera couldn't see contribute little, so occlusion / a limb
    leaving frame doesn't manufacture a false penalty. Falls back to a plain
    mean when nothing is visible.
    """
    w = np.clip(weights, 0.0, 1.0)
    total = float(w.sum())
    if total < 1e-6:
        return float(dist.mean())
    return float((dist * w).sum() / total)


def _dist_to_score(mean_dist: float) -> float:
    """Map mean per-landmark distance (torso-length units) to 0-100."""
    return round(max(0.0, min(100.0, 100.0 * (1.0 - mean_dist / 0.5))), 1)


# --- difficulty (concern #2) -----------------------------------------------

# --- authoring sanity check --------------------------------------------------

# Key bones and the plausible fraction-of-torso band for each (mirror of the
# client's validatePose in frontend/src/lib/audit.ts). Lenient low end (2D
# foreshortening), the high end catches flung landmarks — misdetections.
_BONES: list[tuple[int, int, float, float, str]] = [
    (11, 13, 0.1, 1.4, "L upper arm"),
    (12, 14, 0.1, 1.4, "R upper arm"),
    (13, 15, 0.1, 1.4, "L forearm"),
    (14, 16, 0.1, 1.4, "R forearm"),
    (23, 25, 0.15, 1.6, "L thigh"),
    (24, 26, 0.15, 1.6, "R thigh"),
    (25, 27, 0.15, 1.6, "L shin"),
    (26, 28, 0.15, 1.6, "R shin"),
]


def sanity_check_pose(landmarks: list) -> dict:
    """Server-side validity check for an authored reference pose.

    The Studio runs the same checks client-side for live feedback, but the
    server never trusts a client-computed audit score: a reference published to
    paying students must pass HERE. Returns {ok, issues}.
    """
    issues: list[str] = []
    try:
        arr = _as_landmarks(landmarks, "checkpoint")
    except ValueError as e:
        return {"ok": False, "issues": [str(e)], "warnings": []}
    xy = arr[:, :2]
    if not np.all(np.isfinite(xy)):
        return {"ok": False, "issues": ["non-finite coordinates"], "warnings": []}
    hip = (xy[_L_HIP] + xy[_R_HIP]) / 2.0
    shoulder = (xy[_L_SHOULDER] + xy[_R_SHOULDER]) / 2.0
    torso = float(np.linalg.norm(shoulder - hip))
    if torso <= 1e-3:
        return {"ok": False, "issues": ["degenerate torso"], "warnings": []}
    warnings: list[str] = []
    for a, b, lo, hi, label in _BONES:
        r = float(np.linalg.norm(xy[a] - xy[b])) / torso
        if r > hi:
            # A bone longer than its band is a flung landmark — hard failure.
            issues.append(f"{label} flung ({r:.2f}x torso)")
        elif r < lo:
            # Foreshortening can legitimately collapse a bone — warn only.
            warnings.append(f"{label} collapsed ({r:.2f}x torso)")
    return {"ok": not issues, "issues": issues, "warnings": warnings}


def resolve_threshold(
    difficulty: str | None = None,
    override: float | None = None,
    authored: float | None = None,
) -> float:
    """Resolve the effective 0-100 gate.

    Priority: explicit numeric `override` (client slider, clamped) > named
    `difficulty` level > authored per-checkpoint tolerance > medium default.
    """
    if override is not None:
        return max(_MIN_THRESHOLD, min(_MAX_THRESHOLD, float(override)))
    if difficulty is not None:
        return DIFFICULTY.get(str(difficulty).lower(), DIFFICULTY[DEFAULT_DIFFICULTY])
    if authored is not None:
        return float(authored)
    return DIFFICULTY[DEFAULT_DIFFICULTY]


# --- scoring math (pure numpy, unit-testable without cv2/mediapipe) ---------

def compare_pose(ref_landmarks: list, att_landmarks: list, threshold: float = 75.0) -> dict:
    """Compare a SINGLE checkpoint pose to a single student pose.

    Used by the real-time guided-flow gate. Both poses are validated, normalized
    (translation + scale invariant), and compared in 2D with visibility weighting.
    Returns {score, matched, effective_score, worst_region, region_scores}.
    """
    ref = _norm_points(_as_landmarks(ref_landmarks, "reference"))
    att_arr = _as_landmarks(att_landmarks, "attempt")
    att = _norm_points(att_arr)
    vis = _visibility(att_arr)

    dist = np.linalg.norm(ref - att, axis=1)  # (33,) 2D per-landmark distance

    region_mean = {name: _weighted_mean(dist[idxs], vis[idxs]) for name, idxs in REGIONS.items()}
    region_scores = {n: _dist_to_score(m) for n, m in region_mean.items()}
    score = _dist_to_score(_weighted_mean(dist, vis))
    matched = score >= threshold
    return {
        "score": score,
        "matched": matched,
        # Sub-threshold poses are heavily penalized so they can't aggregate like
        # a real hit; a matched pose keeps its full score.
        "effective_score": score if matched else round(score * FAIL_PENALTY, 1),
        "worst_region": max(region_mean, key=region_mean.get),
        "region_scores": region_scores,
    }


def validate_pose(
    ref_landmarks: list,
    att_landmarks: list,
    difficulty: str | None = DEFAULT_DIFFICULTY,
    override: float | None = None,
    authored: float | None = None,
) -> dict:
    """Score a live pose against a target and ENFORCE the difficulty gate.

    The server-side mirror of the client's validatePose: normalize both poses,
    compare, resolve the threshold (override > difficulty > authored > default),
    and return the match decision plus a penalized effective score. This is the
    single place difficulty is applied, so the gate is never silently skipped.
    """
    threshold = resolve_threshold(difficulty, override, authored)
    result = compare_pose(ref_landmarks, att_landmarks, threshold=threshold)
    result["threshold"] = threshold
    return result


def _resample(seq: np.ndarray, n: int) -> np.ndarray:
    """Linearly resample a (F, 33, D) sequence to (n, 33, D) over normalized time."""
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
    arr = _as_sequence(frames)
    norm = np.stack([_norm_points(arr[i]) for i in range(arr.shape[0])])  # (F, 33, 2)
    return _resample(norm, n)


def compare(reference: dict, attempt: dict, n: int = 64) -> dict:
    """Compare two extracted sequences.

    Returns {score: 0-100, worst_region, region_scores}. Higher score = closer.
    """
    if not reference.get("frames") or not attempt.get("frames"):
        raise ValueError("empty landmark sequence")

    ref = _prepare(reference["frames"], n)      # (n, 33, 2)
    att = _prepare(attempt["frames"], n)

    # per-landmark, per-frame euclidean distance -> (n, 33)
    dist = np.linalg.norm(ref - att, axis=2)

    region_scores: dict[str, float] = {}
    region_mean_dist: dict[str, float] = {}
    for name, idxs in REGIONS.items():
        md = float(dist[:, idxs].mean())
        region_mean_dist[name] = md
        region_scores[name] = _dist_to_score(md)

    worst_region = max(region_mean_dist, key=region_mean_dist.get)
    score = _dist_to_score(float(dist.mean()))

    return {"score": score, "worst_region": worst_region, "region_scores": region_scores}
