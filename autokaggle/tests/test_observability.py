"""Internal diagnostics must never become an organizer or participant capability."""
from types import SimpleNamespace as NS
import copy
import json

from fastapi.testclient import TestClient
import pytest

from autokaggle import observability as obs
from autokaggle.app import create_app
from autokaggle.store import Store, public_project
from autokaggle.tests.test_access import TEST_CODE, sign_in


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "1")
    monkeypatch.setenv("AUTOKAGGLE_ADMIN_ACCESS_CODE", TEST_CODE)
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://testserver")
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    instance = create_app(tmp_path)
    yield instance
    instance.state.pool.shutdown(wait=True)


def test_admin_sees_all_owners_but_no_private_capabilities(app):
    p = app.state.store.create("another-account", "Cross-account challenge")
    p.update(_participant="participant-capability", _seed=12345, _model_calls=2,
             conversation={"organizer_email": "organizer@example.org", "_response_diagnostics": [{"code": "bad_json"}]})
    app.state.store.save(p)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/internal", follow_redirects=False).headers["location"] == "/login?next=/internal"
        assert client.get("/api/internal/projects").status_code == 403
        assert client.get(f"/api/internal/projects/{p['id']}").status_code == 403
        client.cookies.set("autokaggle_owner", "another-account")
        assert client.get("/api/internal/projects").status_code == 403
        assert sign_in(client).status_code == 200
        page = client.get("/internal")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert client.get("/api/projects").json()["projects"] == []
        listing = client.get("/api/internal/projects").json()
        assert listing["total"] == 1 and listing["projects"][0]["id"] == p["id"]
        response = client.get(f"/api/internal/projects/{p['id']}")
        assert response.headers["cache-control"] == "no-store"
        assert "participant-capability" not in response.text and "12345" not in response.text
        assert "organizer@example.org" not in response.text
        assert response.json()["project"]["conversation"]["_response_diagnostics"]
        assert client.get("/api/internal/projects/missing").status_code == 404
        assert client.get("/api/internal/projects?limit=101").status_code == 422
        assert client.get("/api/internal/projects?offset=1").json()["projects"] == []


def test_email_session_and_reviewer_cannot_use_internal_routes(app, monkeypatch):
    with TestClient(app, base_url="https://testserver") as client:
        assert sign_in(client).status_code == 200
        monkeypatch.setattr(app.state.access, "user", lambda request: {"owner": "account_other"})
        assert client.get("/api/internal/projects").status_code == 403
        assert client.get("/api/internal/projects/anything").status_code == 403
        monkeypatch.setattr(app.state.access, "user", lambda request: None)
        client.cookies.clear()
        reviewer = "reviewer-identity"
        p = app.state.store.create("organizer")
        with app.state.store.connection() as con:
            con.execute("INSERT INTO review_grants VALUES (?,?,?)", (reviewer, p["id"], "2099-01-01"))
        client.cookies.set("autokaggle_owner", reviewer)
        assert client.get("/api/internal/projects").status_code == 403


def test_trace_captures_returned_text_and_survives_restart(tmp_path):
    store = Store(tmp_path)
    p = store.create("organizer")
    result = NS(status="completed", model="test-model", output_text='{"answer": 1}',
                output=[NS(type="reasoning", summary=[NS(text="A provider summary.")], content=[], encrypted_content="NEVER_LOG")],
                usage=NS(input_tokens=11, output_tokens=7, output_tokens_details=NS(reasoning_tokens=3)))
    with obs.model_call(p, "scope", "system", "user@example.org sk-secretvalue", "medium", store.save) as trace:
        trace.update(obs.response_record(result))
    saved = store.get(p["id"], "organizer")["_model_traces"][0]
    assert saved["status"] == "completed" and saved["duration_ms"] >= 0
    assert saved["reasoning"] == "A provider summary." and saved["usage"]["reasoning_tokens"] == 3
    assert "NEVER_LOG" not in json.dumps(saved) and "user@example.org" not in saved["input"]
    assert "sk-secretvalue" not in saved["input"]
    assert "_model_traces" not in public_project(p)
    with pytest.raises(RuntimeError):
        with obs.model_call(p, "draft", "system", "input", "high", store.save):
            raise RuntimeError("Never log raw provider errors or sk-private")
    assert p["_model_traces"][-1]["error_type"] == "RuntimeError"
    assert "sk-private" not in json.dumps(p)
    p["_model_traces"].append({"status": "running"})
    store.save(p)
    restarted = Store(tmp_path)
    assert restarted.get(p["id"], "organizer")["_model_traces"][-1]["status"] == "interrupted"


def test_retention_and_missing_reasoning():
    p = {}
    for _ in range(obs.LIMIT + 2):
        with obs.model_call(p, "scope", "x" * 25000, "input", "medium") as trace:
            trace.update(obs.response_record(NS(status="incomplete", output_text="")))
    assert len(p["_model_traces"]) == obs.LIMIT
    assert p["_model_traces"][-1]["status"] == "incomplete"
    assert not p["_model_traces"][-1]["reasoning_available"]
    assert p["_model_traces"][-1]["instructions"].endswith("[truncated]")


def test_scrub_is_recursive_and_does_not_modify_source():
    source = {"_seed": 88, "nested": [{"api_key": "value", "usage": {"input_tokens": 30}, "url": "https://example.org/review?token=private"}]}
    original = copy.deepcopy(source)
    cleaned = obs.scrub(source)
    assert source == original
    assert cleaned["_seed"] == "[redacted]"
    assert cleaned["nested"][0]["usage"]["input_tokens"] == 30
    assert "private" not in cleaned["nested"][0]["url"]


def test_review_snapshot_exposes_settings_and_ledgers_without_mutation_or_tokens(app):
    p = app.state.store.create("other-account")
    p["setup"] = {"competition_type": "prediction", "daily_submission_limit": 10,
                  "submissions_confirmed": True, "organizer_email": "organizer@example.org"}
    p["workflow"] = {"status": "draft", "checks": [{"status": "pending"}], "artifacts": []}
    app.state.store.save(p)
    with app.state.store.connection() as con:
        con.execute("INSERT INTO draft_submissions (project,version,request,fingerprint,day,result,team) VALUES (?,?,?,?,?,?,?)",
                    (p["id"], "v1", "request-1", "private-fingerprint", "2026-10-31", '{"status":"failed"}', "preview"))
        con.execute("INSERT INTO review_tokens (digest,project,version,expires,used,draft) VALUES (?,?,?,?,?,?)",
                    ("never-expose-token-digest", p["id"], "v1", "2026-11-01", 0, "private-draft-hash"))
        before = con.execute("SELECT body FROM projects WHERE id=?", (p["id"],)).fetchone()[0]
    with TestClient(app, base_url="https://testserver") as client:
        sign_in(client)
        response = client.get(f"/api/internal/projects/{p['id']}")
    body = response.json()
    assert body["project"]["setup"]["daily_submission_limit"] == 10
    assert body["project"]["setup"]["organizer_email"] == "[redacted]"
    assert body["project"]["workflow"]["checks"][0]["status"] == "pending"
    assert body["review"]["submissions"]["total"] == 1
    assert body["review"]["review_invitations"]["records"][0]["used"] is False
    assert "never-expose" not in response.text and "private-fingerprint" not in response.text
    assert "private-draft-hash" not in response.text and "organizer@example.org" not in response.text
    with app.state.store.connection() as con:
        assert con.execute("SELECT body FROM projects WHERE id=?", (p["id"],)).fetchone()[0] == before


def test_capture_metadata_and_validation_are_attached_to_the_exact_call():
    p = {"revision": 3, "conversation": {"_pending": {"message_id": "m1", "field": "task"}, "_interview_round": 2}}
    with obs.model_call(p, "scope", "system", "x" * 25000, "medium") as trace:
        trace["provider_status"] = "completed"
    assert trace["trigger"]["message_id"] == "m1" and trace["trigger"]["revision"] == 3
    assert trace["capture"]["input"] == {"original_chars": 25000, "limit_chars": 24000, "truncated": True}
    obs.mark_validation(p, trace["id"], "rejected", 1, "bad_json")
    assert "validation" not in trace
    obs.mark_validation(p, None, "rejected", 1, "bad_json")
    assert trace["validation"]["status"] == "rejected"
    assert trace["status"] == "completed"
