"""Independent regression cases for review links and development submissions."""
from __future__ import annotations

import re
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from autokaggle import conversation, notifications, onboarding_setup, submissions, workflow
from autokaggle.app import create_app
from autokaggle.core.datasets import profile_csv
from autokaggle.examples import load_example
from autokaggle.tests.readiness_fixtures import complete_definition

OWNER_SESSION = "review-test-owner-" + "a" * 32


@pytest.fixture
def review_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.setenv("AUTOKAGGLE_PUBLIC_BASE_URL", "https://testserver")
    monkeypatch.setenv("AUTOKAGGLE_SMTP_PASSWORD", "test-only")
    deliveries = []

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def login(self, *_args):
            pass

        def send_message(self, message):
            deliveries.append(message)
            return {}

    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", FakeSMTP)
    app = create_app(tmp_path / "private")
    store = app.state.store
    project = store.create(OWNER_SESSION, "Review fixture", "Test brief")
    project["_seed"] = 73
    source = store.directory(project["id"]) / "dataset.csv"
    load_example(project, "materials", source)
    project["dataset"] = profile_csv(source)
    onboarding_setup.update(project, {"competition_type": "prediction", "daily_submission_limit": 5,
                                       "submissions_confirmed": True, "organizer_email": "first@example.org"})
    complete_definition(project)
    conversation.make_readme(project, "fixture-draft")
    assert workflow.build(project, store.directory(project["id"]))["status"] == "ready_for_review"
    store.save(project)
    yield app, store, project, deliveries
    app.state.pool.shutdown(wait=True)


def test_malformed_quoted_csv_is_a_counted_invalid_submission(review_fixture):
    _app, store, project, _deliveries = review_fixture
    payload = '_autokaggle_id,prediction\nvalidation-0,"unterminated\n'
    result = submissions.submit(store, project, "malformed-csv", payload)
    assert result["status"] == "invalid"
    assert result["remaining_today"] == 4
    assert submissions.submit(store, project, "malformed-csv", payload) == result
    with store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM draft_submissions WHERE project=?", (project["id"],)).fetchone()[0] == 1


def test_changed_organizer_gets_new_invitation_and_old_token_expires(review_fixture):
    _app, store, project, deliveries = review_fixture
    assert notifications.send_review(store, project)["status"] == "sent"
    old_token = re.search(r"/review#token=([^\s]+)", deliveries[0].get_content())[1]
    onboarding_setup.update(project, {"organizer_email": "second@example.org"})
    conversation.make_readme(project, "revised-draft")
    workflow.build(project, store.directory(project["id"]))
    store.save(project)
    assert notifications.send_review(store, project)["status"] == "sent"
    assert len(deliveries) == 2
    assert str(deliveries[-1]["To"]) == "second@example.org"
    with pytest.raises(ValueError):
        notifications.redeem(store, old_token)


def test_bypass_addition_and_removal_require_new_review_invitations(review_fixture):
    _app, store, project, deliveries = review_fixture
    assert notifications.send_review(store, project)["status"] == "sent"
    old_token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]
    first_version = project["workflow"]["version"]
    item = project["conversation"]["items"]["evaluation"]
    item["bypasses"] = {"uncertainty": {
        "reason": "The organizer accepts the pilot while the uncertainty analysis is refined.",
        "created_at": "2026-10-30T12:00:00+00:00", "updated_at": "2026-10-30T12:00:00+00:00",
    }}
    store.save(project)
    assert workflow.view(project)["status"] == "stale"
    assert notifications.send_review(store, project)["status"] == "not_ready"
    with pytest.raises(ValueError):
        notifications.redeem(store, old_token)

    bypassed = workflow.build(project, store.directory(project["id"]))
    assert bypassed["status"] == "ready_for_review" and bypassed["version"] != first_version
    assert bypassed["definition_readiness"]["bypassed"] == 1
    store.save(project)
    assert notifications.send_review(store, project)["status"] == "sent"
    bypass_token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]
    assert len(deliveries) == 2

    del item["bypasses"]["uncertainty"]
    store.save(project)
    assert workflow.view(project)["status"] == "stale"
    assert notifications.send_review(store, project)["status"] == "not_ready"
    with pytest.raises(ValueError):
        notifications.redeem(store, bypass_token)
    restored = workflow.build(project, store.directory(project["id"]))
    assert restored["status"] == "ready_for_review" and restored["definition_readiness"]["bypassed"] == 0
    store.save(project)
    assert notifications.send_review(store, project)["status"] == "sent"
    assert len(deliveries) == 3


def test_review_login_preserves_existing_organizer_projects(review_fixture):
    app, store, project, deliveries = review_fixture
    other = store.create(OWNER_SESSION, "Another owned challenge")
    notifications.send_review(store, project)
    token = re.search(r"/review#token=([^\s]+)", deliveries[0].get_content())[1]
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("autokaggle_owner", OWNER_SESSION, domain="testserver.local", path="/")
        assert client.get(f"/api/projects/{other['id']}").status_code == 200
        exchanged = client.post("/api/review/exchange", json={"token": token})
        assert exchanged.status_code == 200
        assert exchanged.json()["redirect"] == f"/?project={project['id']}&view=review"
        cookie = exchanged.headers["set-cookie"].lower()
        assert "samesite=lax" in cookie
        assert "httponly" in cookie
        assert "secure" in cookie
        assert client.get(f"/api/projects/{other['id']}").status_code == 200


def test_expired_review_invitation_can_be_sent_again(review_fixture, monkeypatch):
    _app, store, project, deliveries = review_fixture
    notifications.send_review(store, project)
    after_expiry = notifications._utc() + timedelta(hours=25)
    monkeypatch.setattr(notifications, "_utc", lambda: after_expiry)
    assert notifications.send_review(store, project)["status"] == "sent"
    assert len(deliveries) == 2
    new_token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]
    assert notifications.redeem(store, new_token)[1] == project["id"]


def test_invitation_has_one_sign_in_link_and_scoped_artifact_links(review_fixture):
    app, store, project, deliveries = review_fixture
    assert notifications.send_review(store, project)["status"] == "sent"
    body = deliveries[0].get_content()
    token = re.search(r"/review#token=([^\s]+)", body)[1]
    root = f"/api/projects/{project['id']}/workflow"
    assert body.count(token) == 1
    assert "A. Challenge website\nhttps://testserver" + root + "/preview" in body
    assert "B. Research package (ZIP)\nhttps://testserver" + root + "/package" in body
    assert "C. Test the submission service\nhttps://testserver" + root + "/preview#submission" in body
    assert f"https://testserver/?project={project['id']}&view=review" in body
    assert "problem definition, method and deployment, or baseline reproduction" in body
    assert "training-derived validation" in body
    assert "not a final test score" in body
    assert token not in str(project["workflow"]["notification"])

    # Artifact links do not themselves grant access. The single-use sign-in does.
    with TestClient(app, base_url="https://testserver") as client:
        for path in (root + "/preview", root + "/package"):
            assert client.get(path).status_code == 404
        assert client.post("/api/review/exchange", json={"token": token}).status_code == 200
        assert client.get(root + "/preview").status_code == 200
        assert client.get(root + "/package").status_code == 200


def test_email_navigation_cookie_keeps_cross_origin_writes_blocked(review_fixture):
    app, _store, _project, _deliveries = review_fixture
    with TestClient(app, base_url="https://testserver") as client:
        created = client.post("/api/projects", json={"title": "Email navigation"})
        assert created.status_code == 200
        cookie = created.headers["set-cookie"].lower()
        assert "samesite=lax" in cookie
        assert "httponly" in cookie
        assert "secure" in cookie
        root = f"/api/projects/{created.json()['id']}"
        assert client.get(root).status_code == 200
        blocked = client.patch(root + "/setup", headers={"Origin": "https://unrelated.example.org"},
                               json={"organizer_email": "changed@example.org"})
        assert blocked.status_code == 403
        assert client.get(root + "/setup").json()["setup"]["organizer_email"] == ""
        assert client.patch(root + "/setup", headers={"Origin": "https://testserver"},
                            json={"organizer_email": "owner@example.org"}).status_code == 200


def test_redeemed_invitation_does_not_repeat_for_unchanged_draft(review_fixture, monkeypatch):
    _app, store, project, deliveries = review_fixture
    notifications.send_review(store, project)
    token = re.search(r"/review#token=([^\s]+)", deliveries[0].get_content())[1]
    notifications.redeem(store, token)
    assert notifications.send_review(store, project)["status"] == "sent"
    assert len(deliveries) == 1
    after_token_expiry = notifications._utc() + timedelta(hours=25)
    monkeypatch.setattr(notifications, "_utc", lambda: after_token_expiry)
    assert notifications.send_review(store, project)["status"] == "sent"
    assert len(deliveries) == 1


def test_explicit_review_link_renewal_replaces_unused_link_and_keeps_sessions(review_fixture):
    app, store, project, deliveries = review_fixture
    notifications.send_review(store, project)
    first_token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]
    root = f"/api/projects/{project['id']}"
    version = project["workflow"]["version"]
    with TestClient(app, base_url="https://testserver") as invited:
        assert invited.post("/api/review/exchange", json={"token": first_token}).status_code == 200
        assert notifications.send_review(store, project)["status"] == "sent"
        assert len(deliveries) == 1

        renewed = invited.post(root + "/workflow/notify")
        assert renewed.status_code == 200
        assert renewed.json()["notification"]["status"] == "sent"
        assert renewed.json()["version"] == version
        assert len(deliveries) == 2
        replaced_token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]

        assert invited.post(root + "/workflow/notify").status_code == 200
        assert len(deliveries) == 3
        current_token = re.search(r"/review#token=([^\s]+)", deliveries[-1].get_content())[1]
        assert current_token != replaced_token
        with pytest.raises(ValueError):
            notifications.redeem(store, replaced_token)
        assert notifications.redeem(store, current_token)[1] == project["id"]
        assert invited.get(root).status_code == 200
        assert invited.get(root + "/workflow/package").status_code == 200


def test_revised_draft_sends_new_invitation_with_existing_review_session(review_fixture):
    _app, store, project, deliveries = review_fixture
    notifications.send_review(store, project)
    token = re.search(r"/review#token=([^\s]+)", deliveries[0].get_content())[1]
    notifications.redeem(store, token)
    previous_version = project["workflow"]["version"]
    onboarding_setup.update(project, {"daily_submission_limit": 4, "submissions_confirmed": True})
    conversation.make_readme(project, "revised-allowance-draft")
    workflow.build(project, store.directory(project["id"]))
    store.save(project)
    assert project["workflow"]["version"] != previous_version
    assert notifications.send_review(store, project)["status"] == "sent"
    assert len(deliveries) == 2
    assert f"Version: {project['workflow']['version']}" in deliveries[-1].get_content()


def test_review_round_keeps_artifacts_until_feedback_then_requires_rebuild(review_fixture):
    app, store, project, deliveries = review_fixture
    notifications.send_review(store, project)
    token = re.search(r"/review#token=([^\s]+)", deliveries[0].get_content())[1]
    root = f"/api/projects/{project['id']}"
    previous_version = project["workflow"]["version"]
    with TestClient(app, base_url="https://testserver") as invited:
        assert invited.post("/api/review/exchange", json={"token": token}).status_code == 200
        started = invited.post(root + "/conversation/revision", json={"request_id": "review-current-version"})
        assert started.status_code == 200
        assert started.json()["review"]["status"] == "awaiting_request"
        current = invited.get(root + "/workflow").json()
        assert current["status"] == "ready_for_review"
        assert current["version"] == previous_version
        for artifact in ("preview", "package"):
            assert invited.get(root + "/workflow/" + artifact).status_code == 200

        changed = invited.post(root + "/conversation/messages", json={
            "request_id": "review-method-feedback",
            "message": "Methodology: require a linear reference model so we can compare each feature's effect."})
        assert changed.status_code == 200
        assert changed.json()["review"]["status"] == "draft_ready"
        assert invited.get(root).status_code == 200
        assert invited.get(root + "/workflow").json()["status"] == "stale"
        for artifact in ("preview", "package"):
            assert invited.get(root + "/workflow/" + artifact).status_code == 409

        rebuilt = invited.post(root + "/workflow")
        assert rebuilt.status_code == 200
        # Rules mode records the change but cannot certify its scientific
        # completeness. The changed methodology needs a fresh assessment.
        assert rebuilt.json()["status"] == "needs_changes"
        assert rebuilt.json()["version"] != previous_version
        assert any(gap["field"] == "methodology" for gap in rebuilt.json()["definition_readiness"]["blockers"])
        assert invited.post(root + "/workflow/notify").json()["notification"]["status"] == "not_ready"
        assert len(deliveries) == 1
        for artifact in ("preview", "package"):
            assert invited.get(root + "/workflow/" + artifact).status_code == 200
        assert invited.get(root).status_code == 200


def test_submission_token_has_no_organizer_access_and_is_revoked_when_draft_changes(review_fixture):
    app, store, project, _deliveries = review_fixture
    token = submissions.issue_token(store, project)
    root = f"/api/projects/{project['id']}"
    endpoint = f"/api/evaluation/{project['id']}/submissions"
    predictions = (store.directory(project["id"]) / "workflow/private/baseline_predictions.csv").read_text()
    headers = {"Authorization": "Bearer " + token}
    with TestClient(app, base_url="https://testserver") as client:
        for path in (root, root + "/setup", root + "/workflow/package", root + "/workflow/preview"):
            assert client.get(path, headers=headers).status_code == 404
        assert client.patch(root + "/setup", headers=headers, json={"organizer_email": "attacker@example.org"}).status_code == 404
        result = client.post(endpoint, headers=headers, json={"request_id": "token-submission", "predictions_csv": predictions})
        assert result.status_code == 200 and result.json()["scope"] == "development"
        onboarding_setup.update(project, {"daily_submission_limit": 4})
        store.save(project)
        assert client.post(endpoint, headers=headers, json={"request_id": "stale-submission", "predictions_csv": predictions}).status_code == 401


def test_replacing_token_does_not_reset_team_quota_and_retry_does_not_count_twice(review_fixture):
    _app, store, project, _deliveries = review_fixture
    token = submissions.issue_token(store, project)
    predictions = (store.directory(project["id"]) / "workflow/private/baseline_predictions.csv").read_text()
    authenticated, team = submissions.authenticate(store, project["id"], token)
    first = submissions.submit(store, authenticated, "first-attempt", predictions, team)
    assert first["remaining_today"] == 4
    assert submissions.submit(store, authenticated, "first-attempt", predictions, team) == first
    replacement = submissions.issue_token(store, project)
    assert submissions.authenticate(store, project["id"], token) is None
    authenticated, team = submissions.authenticate(store, project["id"], replacement)
    assert submissions.submit(store, authenticated, "second-attempt", predictions, team)["remaining_today"] == 3
    other = store.create(OWNER_SESSION, "Unrelated challenge")
    assert submissions.authenticate(store, other["id"], replacement) is None


def test_private_organizer_address_in_free_text_budget_does_not_enter_public_zip(review_fixture):
    _app, store, project, _deliveries = review_fixture
    project["answers"]["compute_budget"] = "USD 20, confirmed by first@example.org"
    project["answers"]["token_budget"] = "USD 5; ask first@example.org"
    workflow.build(project, store.directory(project["id"]))
    with zipfile.ZipFile(store.directory(project["id"]) / "workflow/researcher.zip") as archive:
        for name in archive.namelist():
            assert b"first@example.org" not in archive.read(name), name


def test_chat_contact_change_revokes_prior_review_session(review_fixture):
    app, store, project, deliveries = review_fixture
    notifications.send_review(store, project)
    token = re.search(r"/review#token=([^\s]+)", deliveries[0].get_content())[1]
    prior_session, _ = notifications.redeem(store, token)
    root = f"/api/projects/{project['id']}"
    with TestClient(app, base_url="https://testserver") as owner_client, TestClient(app, base_url="https://testserver") as prior_reviewer:
        owner_client.cookies.set("autokaggle_owner", OWNER_SESSION, domain="testserver.local", path="/")
        prior_reviewer.cookies.set("autokaggle_owner", prior_session, domain="testserver.local", path="/")
        assert prior_reviewer.get(root).status_code == 200
        changed = owner_client.post(root + "/conversation/messages", json={
            "request_id": "change-contact-in-chat", "message": "Organizer email: second@example.org"})
        assert changed.status_code == 200, changed.text
        assert changed.json()["setup"]["organizer_email"] == "second@example.org"
        assert prior_reviewer.get(root).status_code == 404


def test_completed_code_retry_survives_runner_unavailability(review_fixture, monkeypatch):
    from autokaggle.runner import CivoRunner

    _app, store, project, _deliveries = review_fixture
    expected = (store.directory(project["id"]) / "workflow/private/baseline_predictions.csv").read_bytes()
    calls = []

    def remote(_self, source, **inputs):
        calls.append(source)
        return expected

    monkeypatch.setattr(CivoRunner, "status", lambda _self: {"enabled": True})
    monkeypatch.setattr(CivoRunner, "submit", remote)
    onboarding_setup.update(project, {"competition_type": "code"})
    conversation.make_readme(project, "code-retry-readme")
    workflow.build(project, store.directory(project["id"]))
    first = submissions.submit_code(store, project, "completed-code-attempt", "import csv")
    assert first["status"] == "scored"
    call_count = len(calls)
    monkeypatch.setattr(CivoRunner, "status", lambda _self: {"enabled": False})
    assert submissions.submit_code(store, project, "completed-code-attempt", "import csv") == first
    assert len(calls) == call_count
