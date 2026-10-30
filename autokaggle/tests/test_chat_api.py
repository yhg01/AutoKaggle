"""HTTP boundaries and persistence for the simple onboarding chat."""
from __future__ import annotations

import uuid
from fastapi.testclient import TestClient
import pytest

from autokaggle.app import create_app


@pytest.fixture
def chat_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    app = create_app(tmp_path / "chat-data")
    yield app
    app.state.pool.shutdown(wait=True)


def action(client, root, endpoint, **values):
    response = client.post(root + endpoint, json={"request_id": str(uuid.uuid4()), **values})
    assert response.status_code == 200, response.text
    return response.json()


def new_chat(client, contact=True):
    response = client.post("/api/projects", json={"title": "New challenge"})
    assert response.status_code == 200
    identifier = response.json()["id"]
    if contact:
        assert client.patch(f"/api/projects/{identifier}/setup", json={"organizer_email": "organizer@example.org"}).status_code == 200
    return identifier, f"/api/projects/{identifier}/conversation"


def test_chat_journey_persistence_download_and_owner_boundary(chat_app):
    with TestClient(chat_app) as client:
        _, root = new_chat(client)
        initial = client.get(root).json()
        assert initial["phase"] == "initial"
        assert len(initial["checklist"]) == 17
        assert all(item["understanding"]["score"] == 0 for item in initial["checklist"] if item["owner"] == "researcher" and item["id"] != "organizer")
        assert next(item for item in initial["checklist"] if item["id"] == "trial")["understanding"]["score"] is None
        assert [stage["id"] for stage in initial["interview"]["stages"]] == ["problem", "approach", "baseline"]
        assert initial["mode"] == "rules"
        assert client.get(root + "/readme.md").status_code == 404
        sent = action(client, root, "/messages", message="Predict whether a synthetic material remains stable after a stress test.")
        assert any(message["role"] == "user" for message in sent["messages"])
        learned = next(item for item in sent["checklist"] if item["id"] == "question")
        assert learned["understanding"]["score"] == 0
        assert learned["value"] == "Predict whether a synthetic material remains stable after a stress test."
        reloaded = client.get(root).json()
        assert reloaded["checklist"] == sent["checklist"]
        assert reloaded["interview"]["stages"] == sent["interview"]["stages"]
        active = sent["current_question"]["field"]
        skipped = action(client, root, "/skip")
        assert next(item for item in skipped["checklist"] if item["id"] == active)["status"] == "deferred"
        assert next(item for item in skipped["checklist"] if item["id"] == active)["understanding"]["score"] == 0
        drafted = action(client, root, "/draft")
        assert drafted["phase"] == "draft" and drafted["readme"]
        download = client.get(root + "/readme.md")
        assert download.status_code == 200
        assert download.text == drafted["readme"]
        assert "attachment" in download.headers["content-disposition"]
        assert download.headers["content-type"].startswith("text/markdown")
        assert client.get(root).json()["readme"] == drafted["readme"]
        with TestClient(chat_app) as outsider:
            assert outsider.get(root).status_code == 404
            assert outsider.get(root + "/readme.md").status_code == 404
            assert outsider.post(root + "/messages", json={"request_id": str(uuid.uuid4()), "message": "Change the task"}).status_code == 404


def test_duplicate_send_does_not_duplicate_transcript(chat_app):
    with TestClient(chat_app) as client:
        _, root = new_chat(client)
        payload = {"request_id": str(uuid.uuid4()), "message": "Predict synthetic material stability."}
        first = client.post(root + "/messages", json=payload)
        second = client.post(root + "/messages", json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json()["messages"] == second.json()["messages"]
        assert sum(m["role"] == "user" for m in second.json()["messages"]) == 1


def test_project_response_hides_internal_conversation_records(chat_app):
    with TestClient(chat_app) as client:
        identifier, root = new_chat(client)
        action(client, root, "/messages", message="Predict synthetic material stability.")
        public = client.get(f"/api/projects/{identifier}").json()["conversation"]
        assert "messages" in public and "checklist" in public
        assert not any(key.startswith("_") for key in public)


@pytest.mark.parametrize("payload", [
    {"request_id": "valid-request", "message": "   "},
    {"request_id": "valid-request", "message": "x" * 12001},
    {"request_id": "../invalid/request", "message": "Example"},
    {"message": "Example"},
    {"request_id": "valid-request", "message": "Example", "unexpected": True},
])
def test_invalid_message_preserves_conversation(chat_app, payload):
    with TestClient(chat_app) as client:
        _, root = new_chat(client)
        before = client.get(root).json()
        assert client.post(root + "/messages", json=payload).status_code == 422
        assert client.get(root).json() == before


def test_concurrent_action_is_reported_and_blocked(chat_app):
    with TestClient(chat_app) as client:
        identifier, root = new_chat(client)
        lock = chat_app.state.store.lock(identifier)
        lock.acquire()
        try:
            assert client.get(root).json()["status"] == "working"
            response = client.post(root + "/messages", json={"request_id": str(uuid.uuid4()), "message": "Another attempt"})
            assert response.status_code == 409
        finally:
            lock.release()
        assert client.get(root).json()["status"] != "working"


def test_cross_origin_chat_write_is_rejected(chat_app):
    with TestClient(chat_app) as client:
        _, root = new_chat(client)
        response = client.post(root + "/messages", json={"request_id": str(uuid.uuid4()), "message": "Example"}, headers={"origin": "https://unrelated.example"})
        assert response.status_code == 403


def test_chat_is_home_and_existing_views_remain_available(chat_app):
    with TestClient(chat_app) as client:
        assert "/static/chat.js" in client.get("/").text
        assert "/static/app.js" in client.get("/workbench").text
        assert "/static/app.js" in client.get("/challenge/example").text


def test_email_is_required_before_interview_actions(chat_app):
    with TestClient(chat_app) as client:
        identifier, root = new_chat(client, contact=False)
        before = client.get(root).json()
        assert before["contact_required"] is True
        for endpoint in ("messages", "skip", "draft", "retry", "revision", "continue"):
            payload = {"request_id": "needs-contact-" + endpoint}
            if endpoint == "messages":
                payload["message"] = "Predict stability."
            response = client.post(root + "/" + endpoint, json=payload)
            assert response.status_code == 422
            assert "organizer email" in response.json()["detail"]
        assert client.post(f"/api/projects/{identifier}/workflow").status_code == 422
        assert client.get(root).json() == before
        assert chat_app.state.store.get(identifier, client.cookies.get("autokaggle_owner")).get("_model_calls", 0) == 0
        assert client.patch(f"/api/projects/{identifier}/setup", json={"organizer_email": "bad"}).status_code == 422
        saved = client.patch(f"/api/projects/{identifier}/setup", json={"organizer_email": "organizer@example.org"})
        assert saved.status_code == 200
        assert saved.json()["conversation"]["contact_required"] is False
        assert saved.json()["conversation"]["messages"] == before["messages"]
        assert action(client, root, "/messages", message="Predict material stability.")["messages"][-1]["role"] == "assistant"


def test_removing_email_blocks_new_work_but_preserves_transcript(chat_app):
    with TestClient(chat_app) as client:
        identifier, root = new_chat(client)
        sent = action(client, root, "/messages", message="Predict material stability.")
        cleared = client.patch(f"/api/projects/{identifier}/setup", json={"organizer_email": ""}).json()["conversation"]
        assert cleared["contact_required"] is True
        assert cleared["messages"] == sent["messages"]
        assert client.post(root + "/messages", json={"request_id": "blocked", "message": "Change it"}).status_code == 422


def test_revision_api_is_explicit_idempotent_and_retains_context(chat_app):
    with TestClient(chat_app) as client:
        identifier, root = new_chat(client)
        assert client.post(root + "/revision", json={"request_id": "too-early"}).status_code == 422
        action(client, root, "/messages", message="Predict material stability.")
        drafted = action(client, root, "/draft")
        assert client.get(root).json()["review"]["round"] == 0
        payload = {"request_id": "start-revision"}
        revised = client.post(root + "/revision", json=payload)
        assert revised.status_code == 200
        view = revised.json()
        assert view["review"]["round"] == 1
        assert view["review"]["status"] == "awaiting_request"
        assert view["messages"][:len(drafted["messages"])] == drafted["messages"]
        assert view["messages"][-1]["content"] == view["review"]["prompt"]
        assert client.post(root + "/revision", json=payload).json()["messages"] == view["messages"]
        with TestClient(chat_app) as outsider:
            assert outsider.post(root + "/revision", json={"request_id": "outside-review"}).status_code == 404


def test_working_draft_continue_preserves_context_and_owner_boundary(chat_app):
    with TestClient(chat_app) as client:
        identifier, root = new_chat(client)
        assert client.post(root + "/continue", json={"request_id": "too-early"}).status_code == 422
        action(client, root, "/messages", message="Predict long-term stability of three-planet systems.")
        drafted = action(client, root, "/draft")
        assert drafted["interview"]["can_continue"]
        assert not drafted["readiness"]["ready"]
        response = client.post(root + "/continue", json={"request_id": "continue-required-details"})
        assert response.status_code == 200, response.text
        continued = response.json()
        assert continued["messages"][:len(drafted["messages"])] == drafted["messages"]
        assert continued["interview"]["round"] == 2
        assert continued["phase"] == "conversation"
        assert continued["followups"] == 1
        assert client.post(root + "/continue", json={"request_id": "continue-required-details"}).json() == continued
        assert client.get(root).json() == continued
        assert not continued["interview"]["can_continue"]
        # A second request ID cannot restart the active round or reset its cap.
        again = client.post(root + "/continue", json={"request_id": "reset-active-round"})
        assert again.status_code == 422
        assert client.get(root).json() == continued
        owner = client.cookies.get("autokaggle_owner")
        stored = chat_app.state.store.get(identifier, owner)
        assert stored["conversation"]["_interview_round"] == 2
        with TestClient(chat_app) as outsider:
            assert outsider.post(root + "/continue", json={"request_id": "outside-continue"}).status_code == 404


def test_continue_rejects_cross_origin_and_active_work(chat_app):
    with TestClient(chat_app) as client:
        identifier, root = new_chat(client)
        action(client, root, "/draft")
        response = client.post(root + "/continue", json={"request_id": "cross-origin-continue"},
                               headers={"origin": "https://unrelated.example"})
        assert response.status_code == 403
        lock = chat_app.state.store.lock(identifier)
        lock.acquire()
        try:
            response = client.post(root + "/continue", json={"request_id": "busy-continue"})
            assert response.status_code == 409
        finally:
            lock.release()
        assert client.get(root).json()["interview"]["round"] == 1


def test_required_unknown_remains_open_after_http_draft_and_continue(chat_app):
    with TestClient(chat_app) as client:
        _, root = new_chat(client)
        sent = action(client, root, "/messages", message="Predict long-term planetary stability.")
        unknown_field = sent["current_question"]["field"]
        skipped = action(client, root, "/skip")
        assert any(item["field"] == unknown_field for item in skipped["readiness"]["blockers"])
        action(client, root, "/draft")
        continued = action(client, root, "/continue")
        assert continued["current_question"]["field"] != unknown_field
        assert any(item["field"] == unknown_field for item in continued["readiness"]["blockers"])
        assert not continued["readiness"]["ready"]
