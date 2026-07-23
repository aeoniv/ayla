"""Route tests for the owner entitlement bypass across delivery-service.

The owner authored every movement, so they may fully watch/practice their own
content without a purchase entitlement (the same bypass pose-scoring-service
applies). Without it the Studio can't load the video it just uploaded, and the
owner would be prompted to buy their own content. These tests lock in:

  full_video (Studio / practice video load):
    - owner without entitlement -> signed URL
    - entitled student -> signed URL
    - un-entitled student -> 403
    - missing movement -> 404
  playback progress (12s free-preview cap):
    - owner -> main video never locked, variant never locked
    - un-entitled student -> locked past the cap
"""
from fastapi.testclient import TestClient

from app import main
from app.deps import SessionUser, current_user
from app.routes import movements


class _FakeSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class _FakeDoc:
    def __init__(self, data):
        self._data = data

    def get(self):
        return _FakeSnap(self._data)


class _FakeCollection:
    def __init__(self, data):
        self._data = data

    def document(self, _id):
        return _FakeDoc(self._data)


class _FakeDB:
    def __init__(self, data):
        self._data = data

    def collection(self, _name):
        return _FakeCollection(self._data)


def _make_client(monkeypatch, *, movement, entitled, role, tg_id=42):
    monkeypatch.setattr(movements, "db", lambda: _FakeDB(movement))
    monkeypatch.setattr(movements, "sign", lambda path: f"signed://{path}")
    monkeypatch.setattr(movements, "has_movement_entitlement", lambda uid, mid: entitled)
    monkeypatch.setattr(movements, "has_skip_guidance", lambda uid, mid: False)

    def _fake_user():
        return SessionUser(user_id="u1", telegram_id=tg_id, role=role)

    main.app.dependency_overrides[current_user] = _fake_user
    client = TestClient(main.app)
    return client


def _teardown():
    main.app.dependency_overrides.pop(current_user, None)


_MOVEMENT = {"style_id": "s1", "full_video_path": "movements/m1/full.mp4", "price_stars": 50}


def test_owner_without_entitlement_gets_signed_url(monkeypatch):
    client = _make_client(monkeypatch, movement=_MOVEMENT, entitled=False, role="owner")
    try:
        resp = client.get("/movement/m1/full")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["full_url"] == "signed://movements/m1/full.mp4"
        assert body["style_id"] == "s1"
    finally:
        _teardown()


def test_entitled_student_gets_signed_url(monkeypatch):
    client = _make_client(monkeypatch, movement=_MOVEMENT, entitled=True, role="student")
    try:
        resp = client.get("/movement/m1/full")
        assert resp.status_code == 200, resp.text
        assert resp.json()["full_url"] == "signed://movements/m1/full.mp4"
    finally:
        _teardown()


def test_student_without_entitlement_forbidden(monkeypatch):
    client = _make_client(monkeypatch, movement=_MOVEMENT, entitled=False, role="student")
    try:
        resp = client.get("/movement/m1/full")
        assert resp.status_code == 403
    finally:
        _teardown()


def test_missing_movement_404(monkeypatch):
    client = _make_client(monkeypatch, movement=None, entitled=True, role="owner")
    try:
        resp = client.get("/movement/m1/full")
        assert resp.status_code == 404
    finally:
        _teardown()


# --- playback owner bypass ---------------------------------------------------

def _playback_client(monkeypatch, *, entitled, role, watched=99.0):
    from app.routes import playback

    monkeypatch.setattr(playback, "has_movement_entitlement", lambda uid, mid: entitled)
    monkeypatch.setattr(playback, "has_variant_entitlement", lambda uid, vid: entitled)
    monkeypatch.setattr(playback, "get_watched_seconds", lambda uid, mid: watched)
    monkeypatch.setattr(playback, "record_watched_seconds", lambda uid, mid, secs: watched)

    def _fake_user():
        return SessionUser(user_id="u1", telegram_id=42, role=role)

    main.app.dependency_overrides[current_user] = _fake_user
    return TestClient(main.app)


def test_owner_main_video_never_locked(monkeypatch):
    # Owner has no entitlement and has "watched" well past the 12s cap.
    client = _playback_client(monkeypatch, entitled=False, role="owner", watched=99.0)
    try:
        resp = client.post("/playback/progress", json={"movement_id": "m1", "seconds": 99.0})
        assert resp.status_code == 200, resp.text
        assert resp.json()["locked"] is False
    finally:
        _teardown()


def test_student_main_video_locked_past_cap(monkeypatch):
    client = _playback_client(monkeypatch, entitled=False, role="student", watched=99.0)
    try:
        resp = client.post("/playback/progress", json={"movement_id": "m1", "seconds": 99.0})
        assert resp.status_code == 200, resp.text
        assert resp.json()["locked"] is True
    finally:
        _teardown()


def test_owner_variant_never_locked(monkeypatch):
    client = _playback_client(monkeypatch, entitled=False, role="owner")
    try:
        resp = client.post(
            "/playback/progress",
            json={"movement_id": "m1", "variant_id": "v1", "seconds": 3.0},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["locked"] is False
    finally:
        _teardown()
