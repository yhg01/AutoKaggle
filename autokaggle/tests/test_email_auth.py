"""Email sign-in boundaries. Transport substitutes never count as live delivery."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from autokaggle import access, email_auth, notifications, onboarding_setup
from autokaggle.app import create_app
from autokaggle.tests.test_access import TEST_CODE, challenge, sign_in
from autokaggle.tests.test_workflow_review import review_fixture


@pytest.fixture(autouse=True)
def private_environment(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "1")
    monkeypatch.setenv("AUTOKAGGLE_ADMIN_ACCESS_CODE", TEST_CODE)
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://testserver")


@pytest.fixture
def deliveries(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "email_login_available", lambda: True)
    monkeypatch.setattr(notifications, "send_login_code", lambda email, code: sent.append((email, code)))
    return sent


@pytest.fixture
def app(tmp_path):
    instance = create_app(tmp_path / "email")
    yield instance
    instance.state.pool.shutdown(wait=True)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="https://testserver") as browser:
        yield browser


def request_code(client, email="scientist@example.org"):
    return client.post("/api/access/email/request", json={"email": email}, headers=challenge(client))


def verify_code(client, identifier, code):
    return client.post("/api/access/email/verify", json={"challenge_id": identifier, "code": code}, headers=challenge(client))


def login(client, deliveries, email="scientist@example.org"):
    response = request_code(client, email)
    assert response.status_code == 200
    result = verify_code(client, response.json()["challenge_id"], deliveries[-1][1])
    assert result.status_code == 200
    return result


def test_email_login_creates_private_workspace_and_prefills_private_contact(client, app, deliveries):
    state = client.get("/api/access").json()
    assert state["email_login_available"] is True and state["auth_kind"] == "anonymous"
    result = login(client, deliveries, "Scientist@Example.org")
    assert "Secure" in result.headers["set-cookie"] and "HttpOnly" in result.headers["set-cookie"]
    assert client.get("/api/access").json()["auth_kind"] == "user"
    assert access.ADMIN_COOKIE not in client.cookies and "autokaggle_owner" not in client.cookies
    project = client.post("/api/projects", json={}).json()
    assert project["setup"]["organizer_email"] == "scientist@example.org"
    assert client.get(f"/api/projects/{project['id']}/conversation").json()["contact_required"] is False
    token = client.cookies.get(email_auth.USER_COOKIE)
    with app.state.store.connection() as con:
        code_row = con.execute("SELECT digest FROM email_codes").fetchone()
        session_row = con.execute("SELECT digest,account FROM email_sessions").fetchone()
        body = json.loads(con.execute("SELECT body FROM projects WHERE id=?", (project["id"],)).fetchone()[0])
    assert code_row[0] != deliveries[-1][1] and len(code_row[0]) == 64
    assert session_row[0] == hashlib.sha256(token.encode()).hexdigest()
    assert session_row[1].startswith("account_")
    assert "scientist@example.org" in body["_setup_private_emails"]
    assert "organizer_email" not in onboarding_setup.get(body, include_private=False)


def test_accounts_persist_across_browsers_and_restart(client, app, deliveries, monkeypatch):
    login(client, deliveries)
    own = client.post("/api/projects", json={"title": "Private study"}).json()
    later = time.time() + 61
    monkeypatch.setattr(email_auth.time, "time", lambda: later)
    replacement = create_app(app.state.store.root)
    try:
        with TestClient(replacement, base_url="https://testserver") as second:
            login(second, deliveries, "SCIENTIST@example.org")
            assert second.get(f"/api/projects/{own['id']}").status_code == 200
        with TestClient(replacement, base_url="https://testserver") as other:
            login(other, deliveries, "other@example.org")
            assert other.get(f"/api/projects/{own['id']}").status_code == 404
            assert other.get("/api/projects").json()["projects"] == []
    finally:
        replacement.state.pool.shutdown(wait=True)


def test_resend_invalidates_old_code_without_resetting_guesses(client, deliveries, monkeypatch):
    first = request_code(client).json()
    first_code = deliveries[-1][1]
    wrong = "000001" if first_code != "000001" else "000002"
    for _ in range(3):
        assert verify_code(client, first["challenge_id"], wrong).status_code == 401
    assert request_code(client).status_code == 429
    later = time.time() + 61
    monkeypatch.setattr(email_auth.time, "time", lambda: later)
    second = request_code(client).json()
    assert verify_code(client, first["challenge_id"], first_code).status_code == 410
    second_code = deliveries[-1][1]
    wrong = "000001" if second_code != "000001" else "000002"
    for _ in range(2):
        assert verify_code(client, second["challenge_id"], wrong).status_code == 401
    limited = verify_code(client, second["challenge_id"], second_code)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert request_code(client).status_code == 429


def test_code_expires_and_cannot_be_replayed(client, deliveries, monkeypatch):
    first = request_code(client).json()
    assert verify_code(client, first["challenge_id"], deliveries[-1][1]).status_code == 200
    assert verify_code(client, first["challenge_id"], deliveries[-1][1]).status_code == 410
    second = request_code(client, "another@example.org").json()
    later = time.time() + 601
    monkeypatch.setattr(email_auth.time, "time", lambda: later)
    assert verify_code(client, second["challenge_id"], deliveries[-1][1]).status_code == 410


def test_simultaneous_consumption_creates_only_one_session(app, deliveries):
    auth = app.state.access.email_auth
    issued = auth.request_code("scientist@example.org")
    code = deliveries[-1][1]
    def consume():
        try:
            return auth.verify(issued["challenge_id"], code)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))
    assert sum(isinstance(value, str) for value in results) == 1
    assert 410 in results
    with app.state.store.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM email_sessions").fetchone()[0] == 1


def test_forged_and_expired_sessions_cannot_fall_back_to_account_cookie(client, app, deliveries, monkeypatch):
    login(client, deliveries)
    project = client.post("/api/projects", json={}).json()
    token = client.cookies.get(email_auth.USER_COOKIE)
    identity = app.state.access.email_auth.identity(token)
    client.cookies.clear()
    client.cookies.set("autokaggle_owner", identity["owner"])
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    client.cookies.set(email_auth.USER_COOKIE, "f" * 43)
    assert client.post("/api/projects", json={}).status_code == 401
    client.cookies.set(email_auth.USER_COOKIE, token)
    later = time.time() + email_auth.USER_SESSION_SECONDS + 1
    monkeypatch.setattr(email_auth.time, "time", lambda: later)
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    assert client.get("/", follow_redirects=False).status_code == 303


def test_switching_admin_user_and_another_user_keeps_workspaces_separate(client, app, deliveries):
    assert sign_in(client).status_code == 200
    administrator = client.post("/api/projects", json={}).json()
    login(client, deliveries)
    assert client.get(f"/api/projects/{administrator['id']}").status_code == 404
    first = client.post("/api/projects", json={}).json()
    token = client.cookies.get(email_auth.USER_COOKIE)
    login(client, deliveries, "second@example.org")
    assert app.state.access.email_auth.identity(token) is None
    assert client.get(f"/api/projects/{first['id']}").status_code == 404
    second_token = client.cookies.get(email_auth.USER_COOKIE)
    assert sign_in(client).status_code == 200
    assert app.state.access.email_auth.identity(second_token) is None
    assert client.get("/api/config").json()["auth_kind"] == "admin"
    assert client.get(f"/api/projects/{administrator['id']}").status_code == 200
    assert client.get(f"/api/projects/{first['id']}").status_code == 404


def test_logout_revokes_server_session_and_clears_all_cookies(client, app, deliveries):
    login(client, deliveries)
    token = client.cookies.get(email_auth.USER_COOKIE)
    project = client.post("/api/projects", json={}).json()
    response = client.post("/api/access/logout", json={}, headers=challenge(client))
    assert response.status_code == 200 and response.json()["redirect"] == "/login"
    assert app.state.access.email_auth.identity(token) is None
    assert not any(name in client.cookies for name in (access.ADMIN_COOKIE, email_auth.USER_COOKIE, "autokaggle_owner"))
    client.cookies.set(email_auth.USER_COOKIE, token)
    assert client.get(f"/api/projects/{project['id']}").status_code == 404


@pytest.mark.parametrize("email", ["", "not-email", "a@example.org\r\nBcc:attacker@example.org", None, 1, ["a@example.org"], "a" * 300, "\ud800@example.org"])
def test_invalid_email_does_not_send(client, deliveries, email):
    response = client.post("/api/access/email/request", content=json.dumps({"email": email}), headers=challenge(client))
    assert response.status_code == 400 and deliveries == []


@pytest.mark.parametrize("path,payload", [
    ("/api/access/email/request", {"email": "a@example.org"}),
    ("/api/access/email/verify", {"challenge_id": "x" * 43, "code": "123456"}),
    ("/api/access/logout", {}),
])
def test_all_email_mutations_require_origin_and_csrf(client, deliveries, path, payload):
    assert client.post(path, json=payload).status_code == 403
    headers = challenge(client)
    for update in ({"Origin": "null"}, {"X-CSRF-Token": "wrong"}, {"Sec-Fetch-Site": "cross-site"}):
        assert client.post(path, json=payload, headers={**headers, **update}).status_code == 403
    assert deliveries == []


@pytest.mark.parametrize("body", ["[" * 1500 + "]" * 1500, "x" * 5000, '{"email":"a@example.org","extra":true}', '[]', '{"email":'])
def test_malformed_and_oversized_body_is_bounded(client, deliveries, body):
    assert client.post("/api/access/email/request", content=body, headers=challenge(client)).status_code == 400
    assert deliveries == []


def test_mail_unavailable_or_failed_keeps_codes_unusable(client, app, monkeypatch, deliveries):
    monkeypatch.setattr(notifications, "email_login_available", lambda: False)
    assert client.get("/api/access").json()["email_login_available"] is False
    assert request_code(client).status_code == 503
    monkeypatch.setattr(notifications, "email_login_available", lambda: True)
    def fail(email, code):
        raise notifications.MailUnavailable("Provider response with private information")
    monkeypatch.setattr(notifications, "send_login_code", fail)
    response = request_code(client)
    assert response.status_code == 503 and "Provider" not in response.text
    with app.state.store.connection() as con:
        assert con.execute("SELECT used,delivered FROM email_codes").fetchone() == (1, 0)
    assert sign_in(client).status_code == 200


def test_send_limits_survive_restart_and_bound_all_addresses(app, deliveries, monkeypatch):
    auth = app.state.access.email_auth
    current = [time.time()]
    monkeypatch.setattr(email_auth.time, "time", lambda: current[0])
    monkeypatch.setattr(email_auth, "EMAIL_HOUR_LIMIT", 2)
    monkeypatch.setattr(email_auth, "GLOBAL_HOUR_LIMIT", 3)
    auth.request_code("first@example.org")
    current[0] += 61
    auth.request_code("first@example.org")
    current[0] += 61
    replacement = email_auth.EmailAuth(app.state.store, app.state.access._key)
    with pytest.raises(HTTPException) as limit:
        replacement.request_code("first@example.org")
    assert limit.value.status_code == 429
    replacement.request_code("second@example.org")
    with pytest.raises(HTTPException) as total:
        replacement.request_code("third@example.org")
    assert total.value.status_code == 429 and len(deliveries) == 3


def test_review_grant_cannot_be_used_as_raw_account_capability(review_fixture, deliveries):
    instance, store, project, mail = review_fixture
    assert notifications.send_review(store, project)["status"] == "sent"
    token = re.search(r"/review#token=([^\s]+)", mail[-1].get_content())[1]
    with TestClient(instance, base_url="https://testserver") as browser:
        login(browser, deliveries)
        assert browser.post("/api/review/exchange", json={"token": token}).status_code == 200
        raw_owner = browser.cookies.get("autokaggle_owner")
        assert raw_owner.startswith("account_")
        assert browser.get(f"/api/projects/{project['id']}").status_code == 200
        assert browser.post("/api/access/logout", json={}, headers=challenge(browser)).status_code == 200
        browser.cookies.set("autokaggle_owner", raw_owner)
        assert browser.get(f"/api/projects/{project['id']}").status_code == 404
        login(browser, deliveries, "other@example.org")
        assert browser.get(f"/api/projects/{project['id']}").status_code == 404


def test_stale_email_cookie_does_not_consume_review_link_without_access(review_fixture):
    instance, store, project, mail = review_fixture
    assert notifications.send_review(store, project)["status"] == "sent"
    token = re.search(r"/review#token=([^\s]+)", mail[-1].get_content())[1]
    with TestClient(instance, base_url="https://testserver") as browser:
        browser.cookies.set(email_auth.USER_COOKIE, "stale" * 8 + "xxx", domain="testserver.local", path="/")
        assert browser.post("/api/review/exchange", json={"token": token}).status_code == 200
        assert email_auth.USER_COOKIE not in browser.cookies
        assert browser.get(f"/api/projects/{project['id']}").status_code == 200
        assert browser.get("/api/access").json()["auth_kind"] == "reviewer"
        assert browser.post("/api/projects", json={}).status_code == 401
