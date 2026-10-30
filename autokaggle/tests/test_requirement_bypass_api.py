"""Manual requirement decisions use the same ownership and write boundaries as chat."""
from __future__ import annotations

import copy
import uuid

from fastapi.testclient import TestClient
import pytest

from autokaggle.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    application = create_app(tmp_path / "bypass-data")
    yield application
    application.state.pool.shutdown(wait=True)


def new_chat(client, contact=True):
    identifier = client.post("/api/projects", json={"title": "Bypass test"}).json()["id"]
    if contact:
        response = client.patch(f"/api/projects/{identifier}/setup", json={"organizer_email": "organizer@example.org"})
        assert response.status_code == 200
    return identifier, f"/api/projects/{identifier}/conversation"


def payload(**changes):
    return {"request_id": str(uuid.uuid4()), "field": "question", "requirement_id": "success",
            "reason": "A numeric success threshold needs pilot results. Record this as an organizer decision.", **changes}


def criterion(view, field="question", requirement_id="success"):
    item = next(item for item in view["checklist"] if item["id"] == field)
    return next(entry for entry in item["requirements"] if entry["id"] == requirement_id)


def test_save_reload_retry_edit_and_remove_bypass(app):
    with TestClient(app) as client:
        identifier, root = new_chat(client)
        before = client.get(root).json()
        request = payload()
        response = client.post(root + "/requirements/bypass", json=request)
        assert response.status_code == 200, response.text
        view = response.json()
        assert criterion(view)["status"] == "bypassed"
        assert criterion(view)["bypass"]["reason"] == request["reason"]
        assert view["readiness"]["bypassed"] == 1
        assert view["readiness"]["completed"] == before["readiness"]["completed"] + 1
        assert client.get(root).json() == view
        assert client.post(root + "/requirements/bypass", json=request).json() == view
        conflict = client.post(root + "/requirements/bypass", json={**request, "reason": "A changed reason under the same request."})
        assert conflict.status_code == 422
        assert client.get(root).json() == view
        amended = client.post(root + "/requirements/bypass", json=payload(reason="The organizer accepts an exploratory result for this pilot.")).json()
        assert criterion(amended)["bypass"]["reason"] == "The organizer accepts an exploratory result for this pilot."
        removal = payload(remove=True, reason="")
        response = client.post(root + "/requirements/bypass", json=removal)
        assert response.status_code == 200, response.text
        cleared = response.json()
        assert criterion(cleared)["status"] != "bypassed"
        assert cleared["readiness"]["bypassed"] == 0
        assert client.post(root + "/requirements/bypass", json=removal).json() == cleared
        stored = app.state.store.get(identifier, client.cookies.get("autokaggle_owner"))
        assert stored.get("_model_calls", 0) == 0
        assert not any(key.startswith("_") for key in cleared)


@pytest.mark.parametrize("changes", [
    {"reason": ""}, {"reason": "   "}, {"reason": "x" * 2001}, {"reason": None},
    {"field": "missing"}, {"requirement_id": "missing"},
    {"field": "organizer", "requirement_id": "contact"},
    {"field": "competition", "requirement_id": "choice"},
    {"field": "submissions", "requirement_id": "allowance"},
    {"field": "trial", "requirement_id": "execution"},
    {"field": "difficulty", "requirement_id": "reference"},
    {"remove": "false"}, {"request_id": "bad/id"}, {"actor": "system"},
])
def test_invalid_bypass_cannot_change_project(app, changes):
    with TestClient(app) as client:
        identifier, root = new_chat(client)
        before = copy.deepcopy(app.state.store.get(identifier, client.cookies.get("autokaggle_owner")))
        response = client.post(root + "/requirements/bypass", json=payload(**changes))
        assert response.status_code == 422, response.text
        assert app.state.store.get(identifier, client.cookies.get("autokaggle_owner")) == before


def test_bypass_requires_owner_contact_origin_and_exclusive_access(app):
    with TestClient(app) as client:
        identifier, root = new_chat(client, contact=False)
        assert client.post(root + "/requirements/bypass", json=payload()).status_code == 422
        client.patch(f"/api/projects/{identifier}/setup", json={"organizer_email": "organizer@example.org"})
        before = client.get(root).json()
        with TestClient(app) as outsider:
            assert outsider.post(root + "/requirements/bypass", json=payload()).status_code == 404
        assert client.post(root + "/requirements/bypass", json=payload(), headers={"origin": "https://unrelated.example"}).status_code == 403
        lock = app.state.store.lock(identifier)
        lock.acquire()
        try:
            assert client.post(root + "/requirements/bypass", json=payload()).status_code == 409
        finally:
            lock.release()
        assert client.get(root).json() == before


@pytest.mark.parametrize("change", [
    {"status": "working"}, {"_inflight": True},
    {"_pending": {"kind": "message"}},
    {"_unprocessed": [{"text": "A correction still needs assessment.", "message_id": "pending-test"}]},
])
def test_unfinished_assessment_blocks_bypass(app, change):
    with TestClient(app) as client:
        identifier, root = new_chat(client)
        project = app.state.store.get(identifier, client.cookies.get("autokaggle_owner"))
        from autokaggle.conversation import ensure_conversation
        ensure_conversation(project).update(change)
        app.state.store.save(project)
        response = client.post(root + "/requirements/bypass", json=payload())
        assert response.status_code == 422, response.text
        saved = app.state.store.get(identifier, client.cookies.get("autokaggle_owner"))
        assert saved == project
