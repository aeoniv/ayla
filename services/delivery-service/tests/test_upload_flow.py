"""Route tests for the direct-to-GCS upload flow.

Videos are uploaded by the browser straight to GCS via a signed PUT URL, so the
create endpoints receive only object paths — never file bytes — keeping large
videos off Cloud Run's 32 MiB request path. These tests lock in:

  - /admin/upload-url mints a path under the uploads/ prefix (+ rejects bad kind)
  - create-movement only accepts a teaser/full path under uploads/ (so it can't
    be tricked into referencing an arbitrary bucket object)
  - create-movement rejects a path whose object never actually landed
"""
from fastapi.testclient import TestClient

from app import main
from app.deps import SessionUser, require_owner
from app.routes import admin


def _owner_client(monkeypatch, **patches):
    for name, val in patches.items():
        monkeypatch.setattr(admin, name, val)
    main.app.dependency_overrides[require_owner] = lambda: SessionUser("u1", 42, "owner")
    return TestClient(main.app)


def _teardown():
    main.app.dependency_overrides.pop(require_owner, None)


def test_upload_url_valid(monkeypatch):
    client = _owner_client(monkeypatch, signed_upload_url=lambda path, ct: f"https://signed/{path}")
    try:
        r = client.post("/admin/upload-url", json={"kind": "teaser"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["path"].startswith("uploads/")
        assert body["path"].endswith("/teaser.mp4")
        assert body["url"] == f"https://signed/{body['path']}"
        assert body["content_type"] == "video/mp4"
    finally:
        _teardown()


def test_upload_url_bad_kind(monkeypatch):
    client = _owner_client(monkeypatch, signed_upload_url=lambda path, ct: "x")
    try:
        r = client.post("/admin/upload-url", json={"kind": "banana"})
        assert r.status_code == 400
    finally:
        _teardown()


def test_create_movement_rejects_non_upload_path(monkeypatch):
    client = _owner_client(
        monkeypatch,
        doc_exists=lambda coll, _id: True,
        blob_exists=lambda p: True,
    )
    try:
        r = client.post("/admin/movement", json={
            "name": "X", "style_id": "s1", "price_stars": 50,
            "teaser_path": "movements/evil/teaser.mp4",  # not under uploads/
            "full_path": "uploads/abc/full.mp4",
        })
        assert r.status_code == 400
        assert "uploads" in r.text
    finally:
        _teardown()


def test_create_movement_rejects_missing_upload(monkeypatch):
    client = _owner_client(
        monkeypatch,
        doc_exists=lambda coll, _id: True,
        blob_exists=lambda p: False,  # upload never finished
    )
    try:
        r = client.post("/admin/movement", json={
            "name": "X", "style_id": "s1", "price_stars": 50,
            "teaser_path": "uploads/abc/teaser.mp4",
            "full_path": "uploads/abc/full.mp4",
        })
        assert r.status_code == 400
        assert "upload not found" in r.text
    finally:
        _teardown()


def test_create_movement_unknown_style(monkeypatch):
    client = _owner_client(
        monkeypatch,
        doc_exists=lambda coll, _id: False,  # style doesn't exist
        blob_exists=lambda p: True,
    )
    try:
        r = client.post("/admin/movement", json={
            "name": "X", "style_id": "nope", "price_stars": 50,
            "teaser_path": "uploads/abc/teaser.mp4",
            "full_path": "uploads/abc/full.mp4",
        })
        assert r.status_code == 400
        assert "unknown style_id" in r.text
    finally:
        _teardown()
