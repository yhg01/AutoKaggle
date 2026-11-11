"""Account names must not change scientific records or access rights."""
import copy
import json
import sqlite3
import zipfile

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from autokaggle import conversation, email_auth, notifications, researcher_profiles as profiles, workflow
from autokaggle.app import create_app
from autokaggle.store import Store
from autokaggle.tests.test_access import TEST_CODE, challenge
from autokaggle.tests.test_workflow_review import review_fixture


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "1")
    monkeypatch.setenv("AUTOKAGGLE_ADMIN_ACCESS_CODE", TEST_CODE)
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://testserver")
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.setattr(email_auth, "RESEND_SECONDS", 0)
    deliveries = []
    monkeypatch.setattr(notifications, "email_login_available", lambda: True)
    monkeypatch.setattr(notifications, "send_login_code", lambda email, code: deliveries.append((email, code)))
    app = create_app(tmp_path)
    yield app, deliveries
    app.state.pool.shutdown(wait=True)


def login(client, deliveries, email="researcher@example.org", admin=False):
    sent = client.post("/api/access/email/request", json={"email": email}, headers=challenge(client))
    sent.raise_for_status()
    payload = {"challenge_id": sent.json()["challenge_id"], "code": deliveries[-1][1]}
    if admin:
        payload["access_code"] = TEST_CODE
    response = client.post("/api/access/email/verify", json=payload, headers=challenge(client))
    response.raise_for_status()
    return response.json()


def save(client, name):
    account = client.get("/api/access/profile").json()["account_id"]
    return client.patch("/api/access/profile", json={"name": name, "account_id": account}, headers=challenge(client))


def test_existing_database_and_accounts_keep_their_identity(tmp_path):
    db = tmp_path / "projects.sqlite3"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE email_accounts (id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,created REAL NOT NULL)")
        con.execute("INSERT INTO email_accounts VALUES ('account_old','old@example.org',1)")
    store = Store(tmp_path)
    profiles.set_name(store, "account_old", "Antonio", "account_old")
    Store(tmp_path)
    with store.connection() as con:
        assert con.execute("SELECT * FROM email_accounts").fetchone() == ("account_old", "old@example.org", 1)
        assert con.execute("SELECT name FROM researcher_profiles").fetchone()[0] == "Antonio"


@pytest.mark.parametrize("name", [None, True, 4, [], "", "   ", "x" * 101, "A\nB", "A\x00B", "A\u202eB", "A\ud800B"])
def test_invalid_names_are_rejected(name):
    with pytest.raises(HTTPException) as error:
        profiles.validate_name(name)
    assert error.value.status_code == 400


@pytest.mark.parametrize("name,expected", [("  Éduardo   García  ", "Éduardo García"), ("Jose\u0301", "José"), ("\u674e\u660e", "\u674e\u660e"), ("A. O’Connor-Smith", "A. O’Connor-Smith")])
def test_names_keep_international_spelling(name, expected):
    assert profiles.validate_name(name) == expected


def test_profile_survives_sign_out_and_keeps_saved_session(environment):
    app, deliveries = environment
    with TestClient(app, base_url="https://testserver") as client:
        assert login(client, deliveries)["profile_required"] is True
        token = client.cookies[email_auth.USER_COOKIE]
        owner = app.state.access.email_auth.identity(token)["owner"]
        project = client.post("/api/projects", json={"title": "Halfway through a study"}).json()
        saved = app.state.store.get(project["id"], owner)
        conversation.ensure_conversation(saved)
        saved["conversation"].update(status="error", can_retry=True)
        app.state.store.save(saved)
        before = copy.deepcopy(saved)
        response = save(client, "  Antonio  ")
        assert response.status_code == 200 and response.json()["name"] == "Antonio"
        assert response.headers["cache-control"] == "no-store"
        assert app.state.access.email_auth.identity(token)["owner"] == owner
        assert app.state.store.get(project["id"], owner) == before
        assert client.get("/api/config").json()["researcher_name"] == "Antonio"
        assert client.get("/api/projects").json()["projects"][0]["researcher_name"] == "Antonio"
        client.post("/api/access/logout", json={}, headers=challenge(client)).raise_for_status()
        assert login(client, deliveries)["profile_required"] is False
        assert client.get("/api/access/profile").json()["name"] == "Antonio"
        assert client.get("/api/projects/" + project["id"]).status_code == 200
        assert client.get("/profile").headers["cache-control"] == "no-store"


def test_names_are_private_and_self_updates_need_authentication_and_csrf(environment):
    app, deliveries = environment
    with TestClient(app, base_url="https://testserver") as owner, TestClient(app, base_url="https://testserver") as other:
        assert owner.get("/api/access/profile").status_code == 401
        assert owner.get("/profile", follow_redirects=False).headers["location"].startswith("/login?next=")
        login(owner, deliveries)
        save(owner, "Antonio").raise_for_status()
        project = owner.post("/api/projects", json={}).json()
        assert owner.patch("/api/access/profile", json={"name": "Tampered"}).status_code == 403
        assert owner.patch("/api/access/profile", json={"name": "Changed", "account": "someone-else"}, headers=challenge(owner)).status_code == 400
        login(other, deliveries, "other@example.org")
        save(other, "Antonio").raise_for_status()  # Names are not unique credentials.
        assert other.get("/api/projects/" + project["id"]).status_code == 404
        assert other.patch("/api/access/researcher-profiles/" + project["id"], json={"name": "Impersonated"}, headers=challenge(other)).status_code == 403
        assert owner.get("/api/access/profile").json()["name"] == "Antonio"
        other.cookies.clear()
        assert other.get("/api/config").json()["researcher_name"] == ""
        assert other.get("/api/projects").json()["projects"] == []


def test_account_switch_cannot_rename_the_new_account_from_an_old_form(environment):
    app, deliveries = environment
    with TestClient(app, base_url="https://testserver") as client:
        login(client, deliveries)
        save(client, "Antonio").raise_for_status()
        first = client.get("/api/access/profile").json()["account_id"]
        login(client, deliveries, "another@example.org")
        save(client, "Eduardo").raise_for_status()
        response = client.patch("/api/access/profile", json={"name": "Antonio", "account_id": first}, headers=challenge(client))
        assert response.status_code == 409
        assert client.get("/api/access/profile").json()["name"] == "Eduardo"


def test_admin_can_label_an_existing_account_and_search_all_pages(environment):
    app, deliveries = environment
    with TestClient(app, base_url="https://testserver") as owner, TestClient(app, base_url="https://testserver") as admin:
        login(owner, deliveries)
        project = owner.post("/api/projects", json={"title": "PDE problem"}).json()
        owner_id = app.state.access.email_auth.identity(owner.cookies[email_auth.USER_COOKIE])["owner"]
        saved = app.state.store.get(project["id"], owner_id)
        saved["workflow"] = {"status": "awaiting_approval"}
        app.state.store.save(saved)
        for index in range(55):
            app.state.store.create("legacy-owner", "Newer study " + str(index))
        login(admin, deliveries, "admin@example.org", admin=True)
        endpoint = "/api/access/researcher-profiles/" + project["id"]
        assert admin.patch(endpoint, json={"name": "Antonio"}).status_code == 403
        with app.state.store.connection() as con:
            before = con.execute("SELECT body FROM projects WHERE id=?", (project["id"],)).fetchone()[0]
        response = admin.patch(endpoint, json={"name": "Éduardo García"}, headers=challenge(admin))
        assert response.status_code == 200
        assert owner.get("/api/access/profile").json()["name"] == "Éduardo García"
        result = admin.get("/api/internal/projects", params={"q": "ÉDUARDO"}).json()
        assert result["total"] == 1 and result["projects"][0]["id"] == project["id"]
        assert result["projects"][0]["researcher_name"] == "Éduardo García"
        assert result["projects"][0]["workflow_status"] == "awaiting_approval"
        unfiltered = admin.get("/api/internal/projects", params={"limit": 100}).json()
        matching = next(item for item in unfiltered["projects"] if item["id"] == project["id"])
        assert matching["researcher_name"] == "Éduardo García"
        assert matching["workflow_status"] == "awaiting_approval"
        assert "researcher@example.org" not in json.dumps(result)
        assert admin.get("/api/internal/projects", params={"q": "%"}).json()["total"] == 0
        detail = admin.get("/api/internal/projects/" + project["id"]).json()
        assert detail["researcher"] == {"name": "Éduardo García", "can_edit": True}
        assert "researcher@example.org" not in json.dumps(detail)
        assert admin.patch("/api/access/researcher-profiles/missing", json={"name": "A"}, headers=challenge(admin)).status_code == 404
        legacy = app.state.store.create("legacy-owner")
        assert admin.patch("/api/access/researcher-profiles/" + legacy["id"], json={"name": "A"}, headers=challenge(admin)).status_code == 422
        with app.state.store.connection() as con:
            assert con.execute("SELECT body FROM projects WHERE id=?", (project["id"],)).fetchone()[0] == before


def test_shared_sessions_show_current_names_and_keep_historical_message_labels(environment):
    app, deliveries = environment
    with TestClient(app, base_url="https://testserver") as owner, TestClient(app, base_url="https://testserver") as colleague:
        login(owner, deliveries)
        save(owner, "Antonio").raise_for_status()
        project = owner.post("/api/projects", json={"title": "Shared work", "storage_accepted": True}).json()
        root = "/api/projects/" + project["id"]
        owner.post(root + "/conversation/messages", json={"message": "Predict material stability.", "request_id": "first-owner-answer"}).raise_for_status()
        code = owner.post(root + "/handoff").json()["code"]
        login(colleague, deliveries, "colleague@example.org")
        save(colleague, "Eduardo").raise_for_status()
        colleague.post("/api/handoffs/redeem", json={"code": code, "accepted": True}).raise_for_status()
        members = owner.get(root + "/handoff").json()["members"]
        assert members[0]["name"] == "Eduardo"
        colleague.post(root + "/conversation/messages", json={"message": "Task: produce one label per sample.", "request_id": "colleague-answer"}).raise_for_status()
        messages = owner.get(root + "/conversation").json()["messages"]
        assert next(m for m in messages if m["content"] == "Predict material stability.")["author"] == "Antonio · Organizer"
        assert next(m for m in messages if m["content"] == "Task: produce one label per sample.")["author"].startswith("Eduardo · Collaborator ")
        save(colleague, "Eduardo Updated").raise_for_status()
        assert owner.get(root + "/handoff").json()["members"][0]["name"] == "Eduardo Updated"
        assert owner.get(root + "/conversation").json()["messages"] == messages
        assert colleague.get("/api/projects").json()["projects"][0]["researcher_name"] == "Antonio"


def test_account_profile_is_not_exported_in_participant_materials(review_fixture):
    app, store, project, _deliveries = review_fixture
    name = "ProfileOnlySentinel-Researcher"
    conversation._message(project["conversation"], "user", "A compatible observation.")
    project["conversation"]["messages"][-1]["author"] = name + " · Organizer"
    workflow.build(project, store.directory(project["id"]))
    with zipfile.ZipFile(store.directory(project["id"]) / "workflow/researcher.zip") as archive:
        assert all(name.encode() not in archive.read(item) for item in archive.namelist())
