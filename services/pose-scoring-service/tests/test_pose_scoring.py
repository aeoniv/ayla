"""Unit tests for the pose scoring corrections (numpy-only, no cv2/mediapipe).

Covers the three refactor concerns:
  1. Normalization: translation + scale invariance (camera distance/position).
  2. Difficulty: validate_pose enforces the gate and penalizes misses.
  3. Coordinate mapping: malformed / mis-shaped landmark payloads are rejected.
"""
import numpy as np
import pytest

from app.pose import (
    DIFFICULTY,
    compare_pose,
    resolve_threshold,
    validate_pose,
)

_L_SHOULDER, _R_SHOULDER, _L_HIP, _R_HIP = 11, 12, 23, 24


def _base_pose() -> list[list[float]]:
    """A plausible standing pose: 33 landmarks (x, y, z, visibility)."""
    rng = np.random.default_rng(7)
    pts = rng.uniform(0.35, 0.65, size=(33, 2))
    # Pin the anchor joints to a sane torso so normalization is well-defined.
    pts[_L_SHOULDER] = [0.42, 0.30]
    pts[_R_SHOULDER] = [0.58, 0.30]
    pts[_L_HIP] = [0.45, 0.60]
    pts[_R_HIP] = [0.55, 0.60]
    z = np.zeros((33, 1))
    vis = np.ones((33, 1))
    return np.hstack([pts, z, vis]).tolist()


def _transform(pose, scale, dx, dy):
    """Uniform scale + translation on x,y — 'dancer stood closer / off-centre'."""
    arr = np.asarray(pose, dtype=float).copy()
    arr[:, 0] = arr[:, 0] * scale + dx
    arr[:, 1] = arr[:, 1] * scale + dy
    return arr.tolist()


# --- concern 1: normalization ----------------------------------------------

def test_scale_and_translation_invariant():
    ref = _base_pose()
    live = _transform(ref, scale=1.6, dx=-0.2, dy=0.15)  # same pose, closer + shifted
    r = compare_pose(ref, live)
    assert r["score"] == 100.0, r
    assert r["matched"] is True


def test_different_pose_scores_low():
    ref = _base_pose()
    live = np.asarray(ref, dtype=float).copy()
    # Throw both wrists far from target -> genuinely different pose.
    live[15] = [0.10, 0.05, 0, 1]
    live[16] = [0.90, 0.05, 0, 1]
    r = compare_pose(ref, live.tolist())
    assert r["score"] < 90.0
    assert r["worst_region"] in ("left_arm", "right_arm")


def test_low_visibility_joint_not_penalized():
    ref = _base_pose()
    live = np.asarray(ref, dtype=float).copy()
    # Wrist is badly off BUT marked invisible -> should be largely ignored.
    live[15] = [0.05, 0.02, 0, 0.0]
    r = compare_pose(ref, live.tolist())
    assert r["score"] >= 95.0, r


# --- concern 2: difficulty enforcement -------------------------------------

def test_resolve_threshold_priority():
    assert resolve_threshold(override=200) == 95.0          # clamped
    assert resolve_threshold(override=10) == 30.0           # clamped
    assert resolve_threshold(difficulty="hard") == DIFFICULTY["hard"]
    assert resolve_threshold(authored=62.0) == 62.0
    assert resolve_threshold() == DIFFICULTY["medium"]
    # override beats everything
    assert resolve_threshold(difficulty="easy", override=88) == 88.0


def test_difficulty_gate_and_penalty():
    ref = _base_pose()
    # A moderately-off pose: nudge several joints so score lands mid-range.
    live = np.asarray(ref, dtype=float).copy()
    live[13] += [0.08, 0.05, 0, 0]
    live[14] += [-0.08, 0.05, 0, 0]
    live[25] += [0.06, 0.04, 0, 0]
    live[26] += [-0.06, 0.04, 0, 0]
    live = live.tolist()

    easy = validate_pose(ref, live, difficulty="easy")
    hard = validate_pose(ref, live, difficulty="hard")
    assert easy["threshold"] == DIFFICULTY["easy"]
    assert hard["threshold"] == DIFFICULTY["hard"]
    # Same pose, stricter gate -> harder to pass.
    assert easy["score"] == hard["score"]
    if hard["matched"] is False:
        # Failing the gate crushes the effective score.
        assert hard["effective_score"] < hard["score"]
        assert hard["effective_score"] == round(hard["score"] * 0.35, 1)
    # An easy gate this same pose should clear (or at least not be penalized
    # harder than the hard gate).
    assert easy["effective_score"] >= hard["effective_score"]


def test_validate_pose_falls_back_to_authored_tolerance():
    # The authoritative re-score (services/routes/score.py score_attempt) calls
    # validate_pose with only `authored=` set, relying on it NOT defaulting to
    # the "medium" difficulty gate — regression test for that priority order.
    ref = _base_pose()
    live = _transform(ref, 1.0, 0.0, 0.0)
    r = validate_pose(ref, live, authored=62.0)
    assert r["threshold"] == 62.0


def test_perfect_pose_passes_hardest():
    ref = _base_pose()
    live = _transform(ref, 1.3, 0.1, -0.05)
    r = validate_pose(ref, live, difficulty="hard")
    assert r["matched"] is True
    assert r["effective_score"] == r["score"] == 100.0


# --- concern 3: coordinate mapping guard -----------------------------------

def test_rejects_wrong_landmark_count():
    ref = _base_pose()
    short = ref[:20]  # only 20 landmarks
    with pytest.raises(ValueError):
        compare_pose(ref, short)


def test_rejects_too_few_dims():
    ref = _base_pose()
    flat = [[p[0], p[1]] for p in ref]  # only x,y -> < 3 dims
    with pytest.raises(ValueError):
        compare_pose(ref, flat)


def test_rejects_ragged():
    ref = _base_pose()
    ragged = [list(p) for p in ref]
    ragged[5] = [0.1]  # ragged row
    with pytest.raises(ValueError):
        compare_pose(ref, ragged)


def test_rejects_non_finite_landmarks():
    ref = _base_pose()
    nan_pose = np.asarray(ref, dtype=float).copy()
    nan_pose[15, 0] = float("nan")  # a single NaN coordinate
    with pytest.raises(ValueError):
        compare_pose(ref, nan_pose.tolist())


# --- authoring sanity check + checkpoint building ---------------------------

def test_sanity_check_accepts_plausible_pose():
    res = __import__("app.pose", fromlist=["sanity_check_pose"]).sanity_check_pose(_base_pose())
    assert res["ok"], res


def test_sanity_check_rejects_flung_landmark():
    from app.pose import sanity_check_pose
    pose = _base_pose()
    pose[15][0] += 5.0  # left wrist flung far outside the body
    res = sanity_check_pose(pose)
    assert not res["ok"]
    assert any("flung" in i for i in res["issues"])


def test_sanity_check_rejects_degenerate_and_malformed():
    from app.pose import sanity_check_pose
    assert not sanity_check_pose([[0.5, 0.5, 0, 1]] * 33)["ok"]      # degenerate torso
    assert not sanity_check_pose([[0.5, 0.5, 0, 1]] * 10)["ok"]      # wrong shape
    bad = _base_pose(); bad[0][0] = float("nan")
    assert not sanity_check_pose(bad)["ok"]


def test_build_checkpoints_rejects_duplicate_frames():
    from app.pose import build_checkpoints
    seq = {"frames": [_base_pose(), _base_pose(), _base_pose()],
           "timestamps": [0.0, 1.0, 2.0]}
    out = build_checkpoints(seq, [0.1, 1.1])
    assert [c["timestamp_seconds"] for c in out] == [0.0, 1.0]
    with pytest.raises(ValueError):
        build_checkpoints(seq, [0.9, 1.1])  # both resolve to the 1.0s frame
