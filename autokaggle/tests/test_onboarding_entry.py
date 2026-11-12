"""Both Full entry paths retain the same evidence, access, and evaluator gates."""
from __future__ import annotations

import copy
import io
import zipfile

from fastapi.testclient import TestClient
import pytest

from autokaggle import notifications, workflow
from autokaggle.app import create_app
from autokaggle.tests.readiness_fixtures import complete_definition


@pytest.fixture(params=["scratch", "speedrun"])
def entry_path(request):
    return request.param


@pytest.fixture
def app(tmp_path, monkeypatch):
    from autokaggle.runner import CivoRunner

    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "0")
    monkeypatch.setenv("AUTOKAGGLE_DEFAULT_INTERFACE", "full")
    monkeypatch.setenv("AUTOKAGGLE_REQUIRE_STORAGE_CONSENT", "1")
    monkeypatch.setattr(CivoRunner, "status", lambda self: {"enabled": False})
    monkeypatch.setattr(notifications, "send_review", lambda *_: None)
    monkeypatch.setattr(notifications, "request_approval", lambda *_: None)
    instance = create_app(tmp_path / "data")
    yield instance
    instance.state.pool.shutdown(wait=True)


def create(client, accepted=True):
    response = client.post("/api/projects", json={"storage_accepted": accepted})
    response.raise_for_status()
    root = "/api/projects/" + response.json()["id"]
    return root


@pytest.fixture
def ready_case(app, entry_path):
    with TestClient(app) as client:
        root = create(client)
        client.patch(root + "/onboarding", json={"entry_path": entry_path}).raise_for_status()
        client.post(root + "/example", json={"name": "materials"}).raise_for_status()
        client.patch(root + "/setup", json={
            "competition_type": "prediction", "daily_submission_limit": 5,
            "submissions_confirmed": True, "organizer_email": "entry-test@example.org",
        }).raise_for_status()
        identifier = root.rsplit("/", 1)[1]
        item = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
        complete_definition(item)["readme"] = "# A private synthetic challenge\n"
        app.state.store.save(item)
        yield app, client, root, identifier


def build(client, root):
    response = client.post(root + "/workflow", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_entry_choice_preserves_definition_and_setup(app, entry_path):
    with TestClient(app) as client:
        root = create(client)
        before = client.get(root + "/conversation").json()
        response = client.patch(root + "/onboarding", json={"entry_path": entry_path})
        response.raise_for_status()
        after = response.json()
        assert after["entry_path"] == entry_path
        for key in ("readiness", "checklist", "setup", "messages"):
            assert after[key] == before[key]
        assert after["readiness"]["ready"] is False
        assert client.get(root + "/conversation").json()["entry_path"] == entry_path
        item = app.state.store.get(root.rsplit("/", 1)[1], client.cookies["autokaggle_owner"])
        assert "lite" not in item


@pytest.mark.parametrize("extra", [{"lite": True}, {"trust_mode": "internal"}, {"ready": True}])
def test_entry_choice_rejects_trust_and_readiness_overrides(app, entry_path, extra):
    with TestClient(app) as client:
        root = create(client)
        assert client.patch(root + "/onboarding", json={"entry_path": entry_path, **extra}).status_code == 422
        assert client.get(root + "/conversation").json()["entry_path"] is None


@pytest.mark.parametrize("value", ["lite", "internal", "full", "", None, True])
def test_entry_choice_rejects_invalid_values(app, value):
    with TestClient(app) as client:
        root = create(client)
        assert client.patch(root + "/onboarding", json={"entry_path": value}).status_code == 422


def test_entry_choice_requires_storage_and_project_access(app, entry_path):
    with TestClient(app) as owner, TestClient(app) as stranger:
        root = create(owner, accepted=False)
        assert owner.patch(root + "/onboarding", json={"entry_path": entry_path}).status_code == 428
        assert stranger.patch(root + "/onboarding", json={"entry_path": entry_path}).status_code == 404
        assert owner.get(root + "/conversation").json()["entry_path"] is None


def test_entry_choice_cannot_convert_internal_project(app, entry_path):
    with TestClient(app) as client:
        response = client.post("/api/lite/projects", json={
            "organizer_email": "internal-test@example.org", "storage_accepted": True,
        })
        response.raise_for_status()
        root = "/api/projects/" + response.json()["id"]
        assert client.patch(root + "/onboarding", json={"entry_path": entry_path}).status_code == 409
        assert client.get(root + "/lite").status_code == 200


def test_entry_choice_waits_for_source_import(app, entry_path):
    with TestClient(app) as client:
        root = create(client)
        identifier = root.rsplit("/", 1)[1]
        item = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
        item["_source_import"] = {"status": "working"}
        app.state.store.save(item)
        assert client.patch(root + "/onboarding", json={"entry_path": entry_path}).status_code == 409


def test_entry_change_keeps_saved_interview_and_evidence(app, entry_path):
    with TestClient(app) as client:
        root = create(client)
        client.patch(root + "/setup", json={"organizer_email": "entry-test@example.org"}).raise_for_status()
        client.post(root + "/conversation/messages", json={
            "message": "Predict molecular solubility from chemical structure.",
            "request_id": "entry-existing-answer",
        }).raise_for_status()
        before = client.get(root + "/conversation").json()
        client.patch(root + "/onboarding", json={"entry_path": entry_path}).raise_for_status()
        after = client.get(root + "/conversation").json()
        for key in ("messages", "checklist", "readiness", "setup"):
            assert after[key] == before[key]


@pytest.mark.parametrize("declaration", [{"labels_public": "yes"}, {"rights": "unknown"}])
def test_both_entries_keep_private_answer_and_permission_gates(ready_case, declaration):
    _app, client, root, _identifier = ready_case
    client.patch(root, json={"answers": declaration}).raise_for_status()
    result = build(client, root)
    assert result["status"] == "needs_changes"
    assert next(check for check in result["checks"] if check["id"] == "data")["status"] == "blocked"
    with zipfile.ZipFile(io.BytesIO(client.get(root + "/workflow/package").content)) as archive:
        assert not {"train.csv", "test_features.csv", "validation_features.csv"} & set(archive.namelist())


def test_both_entries_keep_required_scientific_decisions(ready_case):
    instance, client, root, identifier = ready_case
    item = instance.state.store.get(identifier, client.cookies["autokaggle_owner"])
    item["conversation"]["items"]["question"]["requirements"] = {}
    instance.state.store.save(item)
    result = build(client, root)
    assert result["status"] != "ready_for_review"
    assert next(check for check in result["checks"] if check["id"] == "scope")["status"] == "blocked"


def test_both_entries_reject_failed_scorer(ready_case, monkeypatch):
    _instance, client, root, _identifier = ready_case
    monkeypatch.setattr(workflow, "score_file", lambda *_: {"metric": "balanced_accuracy", "score": 0.5, "rows": 10})
    response = client.post(root + "/workflow", json={})
    assert response.status_code == 422
    assert "perfect-answer check" in response.text


def test_both_entries_keep_runner_disabled_and_inputs_private(ready_case):
    instance, client, root, identifier = ready_case
    client.patch(root + "/setup", json={"competition_type": "code"}).raise_for_status()
    client.post(root + "/conversation/draft", json={"request_id": "entry-code-draft"}).raise_for_status()
    result = build(client, root)
    assert result["status"] == "needs_changes"
    assert next(check for check in result["checks"] if check["id"] == "runner")["status"] == "blocked"
    with zipfile.ZipFile(io.BytesIO(client.get(root + "/workflow/package").content)) as archive:
        assert not {"test_features.csv", "validation_features.csv", "test_truth.csv"} & set(archive.namelist())
    response = client.post(root + "/workflow/code-submissions", json={
        "request_id": "disabled-runner-entry-test", "source_code": "raise RuntimeError('must never run')",
    })
    assert response.status_code == 503
    with instance.state.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM draft_submissions WHERE project=?", (identifier,)).fetchone()[0] == 0


def test_entry_change_does_not_change_built_evaluation(ready_case, entry_path):
    instance, client, root, identifier = ready_case
    before = build(client, root)
    stored = instance.state.store.get(identifier, client.cookies["autokaggle_owner"])
    definition = copy.deepcopy(stored["conversation"])
    other = "scratch" if entry_path == "speedrun" else "speedrun"
    client.patch(root + "/onboarding", json={"entry_path": other}).raise_for_status()
    after = client.get(root + "/workflow").json()
    assert after["version"] == before["version"]
    assert after["status"] == before["status"]
    assert instance.state.store.get(identifier, client.cookies["autokaggle_owner"])["conversation"] == definition


def test_full_root_uses_saved_internal_project_type(app):
    with TestClient(app) as client:
        response = client.post("/api/lite/projects", json={
            "organizer_email": "internal-test@example.org", "storage_accepted": True,
        })
        response.raise_for_status()
        identifier = response.json()["id"]
        result = client.get("/?project=" + identifier, follow_redirects=False)
        assert result.status_code == 303
        assert result.headers["location"] == "/lite?project=" + identifier
