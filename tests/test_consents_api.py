"""End-to-end smoke for the /consents endpoint family.

Guest behaviour (Phase A — no AUTH_PROVIDER set): every consent endpoint
returns 401 because consent only makes sense once we know who's
agreeing. The in-memory store is exercised by stubbing get_current_user
in a sub-test.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def app_client(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("consents_data")
    os.environ["RECHORD_DATA_DIR"] = str(data_dir)
    os.environ["RECHORD_PREWARM_AT_BOOT"] = "0"
    try:
        from fastapi.testclient import TestClient
        from backend.app.main import app
    except Exception as e:
        pytest.skip(f"backend import failed: {e!r}")
    with TestClient(app) as c:
        yield c, app


# ── Guest path: every endpoint 401s ──────────────────────────────


def test_guest_post_returns_401(app_client):
    c, _app = app_client
    r = c.post("/consents", json={
        "consent_type": "tos", "version": "2026-05-28-v0.1", "granted": True,
    })
    assert r.status_code == 401, r.text


def test_guest_get_me_returns_401(app_client):
    c, _app = app_client
    assert c.get("/consents/me").status_code == 401


def test_guest_delete_returns_401(app_client):
    c, _app = app_client
    assert c.delete("/consents/tos").status_code == 401


# ── Authenticated path: stub get_current_user ───────────────────


def _authed_client(app, user_id: str = "test-user-1"):
    """Override the auth dependency so the rest of the suite can run
    against a known user without spinning up a real OAuth flow."""
    from fastapi.testclient import TestClient
    from backend.app.auth.auth import get_current_user, User

    async def _fake_user():
        return User(id=user_id, email=f"{user_id}@example.com", name="test")

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_authed_grant_then_list_then_revoke(app_client):
    _c, app = app_client
    from fastapi.testclient import TestClient
    from backend.app.auth.auth import get_current_user, User

    async def _fake_user():
        return User(id="user-flow", email="u@example.com", name="u")

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        c = TestClient(app)
        v = "2026-05-28-v0.1"

        r = c.post("/consents", json={
            "consent_type": "tos", "version": v, "granted": True,
        })
        assert r.status_code == 200, r.text
        assert r.json()["consent_type"] == "tos"
        assert r.json()["granted"] is True
        assert r.json()["revoked_at"] is None

        # Idempotent re-grant
        r2 = c.post("/consents", json={
            "consent_type": "tos", "version": v, "granted": True,
        })
        assert r2.status_code == 200

        # Add a second consent
        c.post("/consents", json={
            "consent_type": "privacy", "version": v, "granted": True,
        })

        listed = c.get("/consents/me").json()
        types = {row["consent_type"] for row in listed}
        assert "tos" in types and "privacy" in types

        # Revoke tos
        r3 = c.delete("/consents/tos")
        assert r3.status_code == 200
        assert r3.json()["revoked"] >= 1

        # After revoke, list still shows the row (audit trail) but revoked_at is set
        after = c.get("/consents/me").json()
        tos_row = next(row for row in after if row["consent_type"] == "tos")
        assert tos_row["revoked_at"] is not None
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_authed_unknown_consent_type_returns_422(app_client):
    _c, app = app_client
    from fastapi.testclient import TestClient
    from backend.app.auth.auth import get_current_user, User

    async def _fake_user():
        return User(id="user-bad", email=None, name=None)

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        c = TestClient(app)
        r = c.post("/consents", json={
            "consent_type": "delete_everything",
            "version": "v1",
            "granted": True,
        })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)
