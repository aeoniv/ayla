"""Route tests for GET /movement/{id}/full entitlement gating.

The Studio loads the full reference video via this endpoint the moment a new
course is created. The owner has no *purchase* entitlement for their own
freshly-uploaded movement, so without an owner bypass authoring is impossible
(the Studio dies with 403 "entitlement required"). These tests lock in:

  - owner  -> gets the signed URL even with no entitlement (authoring works)
  - student with entitlement -> gets the signed URL
  - student without entitlement -> 403
  - missing movement -> 404
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
