"""Private deployment authentication and project access boundaries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import time

from fastapi.testclient import TestClient
import pytest

from autokaggle import access, notifications
from autokaggle.app import create_app
from autokaggle.tests.test_workflow_review import review_fixture

TEST_CODE = "test-only-administrator-code-" + "x" * 32


@pytest.fixture(autouse=True)
def private_environment(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "1")
    monkeypatch.setenv("AUTOKAGGLE_ADMIN_ACCESS_CODE", TEST_CODE)
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://testserver")


@pytest.fixture
def app(tmp_path):
    instance = create_app(tmp_path / "private")
    yield instance
    instance.state.pool.shutdown(wait=True)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="https://testserver") as browser:
        yield browser


def challenge(client):
    response = client.get("/api/access")
    assert response.status_code == 200
    return {"Origin": "https://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def sign_in(client, code=TEST_CODE):
    return client.post("/api/access/login", json={"access_code": code}, headers=challenge(client))


def test_private_mode_requires_a_sufficient_access_code(tmp_path, monkeypatch):
    for code in ("", "too-short"):
        monkeypatch.setenv("AUTOKAGGLE_ADMIN_ACCESS_CODE", code)
        with pytest.raises(RuntimeError, match="administrator access code"):
            create_app(tmp_path)


def test_local_default_keeps_existing_creation_behavior(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOKAGGLE_PRIVATE_MODE")
    monkeypatch.delenv("AUTOKAGGLE_ADMIN_ACCESS_CODE")
    instance = create_app(tmp_path)
    try:
        with TestClient(instance, base_url="https://testserver") as browser:
            assert browser.get("/").status_code == 200
            assert browser.post("/api/projects", json={}).status_code == 200
            assert browser.get("/api/config").json()["can_create_projects"] is True
    finally:
        instance.state.pool.shutdown(wait=True)


def test_anonymous_and_forged_owner_cannot_create_or_open_workspace(client):
    for path in ("/", "/workbench", "/?project=example&view=review"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login?next=")
        assert response.headers["cache-control"] == "no-store"
    client.cookies.set("autokaggle_owner", "forged-owner-" + "x" * 40)
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/api/projects", json={}).status_code == 401
    assert client.get("/api/projects").json() == {"projects": []}
    assert client.get("/api/config").json()["can_create_projects"] is False
    assert client.get("/login").status_code == 200
    assert client.get("/review").status_code == 200
    assert client.get("/review").headers["cache-control"] == "no-store"
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 404


def test_admin_can_create_and_sign_in_again_with_same_projects(client, app):
    response = sign_in(client)
    assert response.status_code == 200
    cookie = next(value for value in response.headers.get_list("set-cookie") if value.startswith(access.ADMIN_COOKIE + "="))
    assert all(value in cookie.lower() for value in ("httponly", "secure", "samesite=lax", "path=/"))
    assert f"Max-Age={access.SESSION_SECONDS}" in cookie
    assert TEST_CODE not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/").status_code == 200
    assert client.get("/api/config").json()["can_create_projects"] is True
    project = client.post("/api/projects", json={"title": "Private challenge"}).json()
    with TestClient(app, base_url="https://testserver") as second_browser:
        assert sign_in(second_browser).status_code == 200
        assert second_browser.get(f"/api/projects/{project['id']}").status_code == 200
        assert second_browser.get("/api/projects").json()["projects"][0]["id"] == project["id"]


def test_secure_cookies_follow_public_https_address_behind_http(app):
    with TestClient(app, base_url="http://testserver") as upstream:
        response = upstream.get("/api/access")
        assert "Secure" in response.headers["set-cookie"]


def test_static_assets_require_validation_after_deployment(client):
    response = client.get("/static/chat.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    unchanged = client.get("/static/chat.js", headers={"If-None-Match": response.headers["etag"]})
    assert unchanged.status_code == 304
    assert unchanged.headers["cache-control"] == "no-cache"
    assert client.get("/api/access").headers["cache-control"] == "no-store"
    assert client.get("/login").headers["cache-control"] == "no-store"


def test_invalid_access_code_does_not_create_session_and_is_throttled(client):
    headers = challenge(client)
    for _ in range(access.ATTEMPT_LIMIT):
        response = client.post("/api/access/login", json={"access_code": "wrong"}, headers=headers)
        assert response.status_code == 401
        assert access.ADMIN_COOKIE not in client.cookies
    denied = client.post("/api/access/login", json={"access_code": TEST_CODE}, headers=headers)
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == str(access.ATTEMPT_WINDOW)
    assert client.post("/api/projects", json={}).status_code == 401


@pytest.mark.parametrize("origin", [None, "null", "https://other.example", "http://testserver"])
def test_sign_in_requires_exact_origin(client, origin):
    headers = challenge(client)
    if origin is None:
        headers.pop("Origin")
    else:
        headers["Origin"] = origin
    assert client.post("/api/access/login", json={"access_code": TEST_CODE}, headers=headers).status_code == 403
    assert access.ADMIN_COOKIE not in client.cookies


def test_sign_in_requires_current_csrf_token(client, monkeypatch):
    headers = challenge(client)
    assert client.post("/api/access/login", json={"access_code": TEST_CODE}, headers={"Origin": "https://testserver"}).status_code == 403
    changed = {**headers, "X-CSRF-Token": "wrong"}
    assert client.post("/api/access/login", json={"access_code": TEST_CODE}, headers=changed).status_code == 403
    later = time.time() + access.CSRF_SECONDS + 1
    monkeypatch.setattr(access.time, "time", lambda: later)
    # Send the expired value explicitly to test the server, not cookie-jar expiry.
    headers["Cookie"] = f"{access.CSRF_COOKIE}={headers['X-CSRF-Token']}"
    assert client.post("/api/access/login", json={"access_code": TEST_CODE}, headers=headers).status_code == 403


def test_expired_admin_cannot_create_but_keeps_existing_project(client, monkeypatch):
    assert sign_in(client).status_code == 200
    project = client.post("/api/projects", json={}).json()
    token = client.cookies.get(access.ADMIN_COOKIE)
    later = time.time() + access.SESSION_SECONDS + 1
    monkeypatch.setattr(access.time, "time", lambda: later)
    assert client.post("/api/projects", json={}, headers={"Cookie": f"{access.ADMIN_COOKIE}={token}"}).status_code == 401
    assert client.get(f"/api/projects/{project['id']}").status_code == 200
    assert client.get("/", follow_redirects=False).status_code == 200


def test_modified_session_signature_cannot_create(client):
    assert sign_in(client).status_code == 200
    token = client.cookies.get(access.ADMIN_COOKIE)
    client.cookies.clear()
    client.cookies.set(access.ADMIN_COOKIE, token[:-1] + ("a" if token[-1] != "a" else "b"))
    assert client.post("/api/projects", json={}).status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("body", [[], {}, {"access_code": 123}, {"access_code": "\ud800"}, {"access_code": "x" * 5000}])
def test_malformed_login_body_is_safe(client, body):
    assert client.post("/api/access/login", content=json.dumps(body), headers=challenge(client)).status_code == 400


def test_deeply_nested_login_json_is_rejected(client):
    response = client.post("/api/access/login", content="[" * 1500 + "]" * 1500, headers=challenge(client))
    assert response.status_code == 400


def test_review_exchange_keeps_access_scoped_and_cannot_create(review_fixture):
    app, store, project, deliveries = review_fixture
    other = store.create("other-owner", "Other private challenge")
    assert notifications.send_review(store, project)["status"] == "sent"
    token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]
    with TestClient(app, base_url="https://testserver") as reviewer:
        assert reviewer.get("/review").status_code == 200
        assert reviewer.post("/api/review/exchange", json={"token": token}).status_code == 200
        assert reviewer.get(f"/api/projects/{project['id']}").status_code == 200
        assert reviewer.get(f"/api/projects/{other['id']}").status_code == 404
        assert reviewer.get("/").status_code == 200
        assert reviewer.get("/workbench").status_code == 200
        assert reviewer.get("/api/config").json()["can_create_projects"] is False
        assert reviewer.post("/api/projects", json={}).status_code == 401
        assert [item["id"] for item in reviewer.get("/api/projects").json()["projects"]] == [project["id"]]
        with store.connection() as connection:
            connection.execute("UPDATE review_grants SET expires=?", ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
        assert reviewer.get(f"/api/projects/{project['id']}").status_code == 404
        assert reviewer.get("/", follow_redirects=False).status_code == 303


def test_review_exchange_preserves_admin_projects(review_fixture):
    app, store, project, deliveries = review_fixture
    assert notifications.send_review(store, project)["status"] == "sent"
    token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]
    with TestClient(app, base_url="https://testserver") as admin:
        assert sign_in(admin).status_code == 200
        own = admin.post("/api/projects", json={"title": "Admin project"}).json()
        assert admin.post("/api/review/exchange", json={"token": token}).status_code == 200
        assert admin.get(f"/api/projects/{own['id']}").status_code == 200
        assert admin.get(f"/api/projects/{project['id']}").status_code == 200
        assert admin.get("/api/config").json()["can_create_projects"] is True
