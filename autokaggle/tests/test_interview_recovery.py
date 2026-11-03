"""Natural corrections and checkpoints remain recoverable after interruption."""
import copy

from fastapi.testclient import TestClient
import pytest

from autokaggle import conversation as c, readiness
from autokaggle.app import create_app
from autokaggle.tests.test_conversation import provider, requirement, scope, update


OLD = "Additionally, well known kernels (i.e top hat) will be used"
PARAMETERS = "Use frequencies k in [1,2,3,4,5,6,7,8,9,10], amplitudes a in [1,2,3,4,5,6,7,8,9,10], and 1, 2 or 3 Fourier modes."
CORRECTION = "don't use top hat then, just use the fourier constructions"


def kernel_project():
    project = {"title": "Kernel scope recovery fixture", "answers": {}, "_model_calls": 0}
    state = c.ensure_conversation(project)
    for text in (PARAMETERS, OLD):
        c._message(state, "user", text)
        c._apply(state, [{**update("data", text), "supersedes": []}], state["messages"][-1]["id"])
    state["items"]["data"]["requirements"] = {"source": {
        "status": "missing", "value": PARAMETERS + "\n" + OLD,
        "evidence": [PARAMETERS, OLD], "reason": "The top-hat construction still needs parameters."}}
    state["_requirements_assessed"] = True
    state["_criterion_asks"]["data.source"] = 2
    c._checkpoint(state, "data", readiness.REQUIREMENTS["data"][0])
    return project


@pytest.mark.parametrize("text", [CORRECTION, "Don’t use top hat.", "Do not include top hat.",
    "Remove top hat from the task.", "Exclude top hat.", "Only use Fourier kernels.",
    "Use only Fourier kernels.", "No longer use top hat.", "Stop considering top hat.",
    "算了，不要 top hat，只用傅里叶构造", "Let's go with the Fourier constructions alone."])
def test_natural_correction_is_applied_without_special_keyword(monkeypatch, text):
    project = kernel_project()
    response = scope([{**update("data", text), "operation": "correct", "supersedes": [OLD]}],
        "data", "How will the reference outcomes be generated?",
        [requirement("data", "source", text)])
    response.update(question_requirement_id="outcomes", question_why="The score needs reference outcomes.")
    calls = provider(monkeypatch, [response])
    c.submit_message(project, text, "natural-correction")
    state = project["conversation"]
    assert state["status"] == "idle" and len(calls) == 1
    assert OLD not in state["items"]["data"]["value"]
    assert PARAMETERS in state["items"]["data"]["value"]
    assert text in state["items"]["data"]["value"]
    assert OLD in state["_superseded_evidence"]
    assert state["current_question"]["requirement_id"] == "outcomes"
    notice = next(m["content"] for m in state["messages"] if m["role"] == "assistant" and m["content"].startswith("I replaced"))
    assert OLD in notice and text in notice


def test_correction_must_name_exact_recorded_text():
    state = kernel_project()["conversation"]
    text = "Drop the wavelet kernels."
    response = scope([{**update("data", text), "operation": "correct", "supersedes": ["wavelet kernels will be used"]}])
    with pytest.raises(ValueError, match="exact, unique prior spans"):
        c._validate_scope(response, text, state)


def test_appended_detail_produces_no_correction_notice():
    assert c._correction_notice([update("data", "Here are more Fourier parameters.")]) is None


def test_checkpoint_reason_changes_do_not_repeat_generic_prompt():
    state = kernel_project()["conversation"]
    before = len(state["messages"])
    state["items"]["data"]["requirements"]["source"]["reason"] = "A different specific source gap."
    c._checkpoint(state, "data", readiness.REQUIREMENTS["data"][0])
    assert len(state["messages"]) == before
    c._message(state, "user", "Here is more information.")
    c._checkpoint(state, "data", readiness.REQUIREMENTS["data"][0])
    assert state["messages"][-1]["content"].startswith("Your update is saved.")
    assert sum(m["content"].startswith("We have not resolved") for m in state["messages"]) == 1


def test_checkpoint_can_be_left_open_without_being_completed(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    project = kernel_project(); state = project["conversation"]
    c.skip_question(project, "leave-checkpoint-open")
    assert state["items"]["data"]["requirements"]["source"]["status"] == "deferred"
    assert state["_criterion_asks"]["data.source"] == 2
    assert not c.conversation_view(project)["readiness"]["ready"]
    assert not state["scope_checkpoint"]
    assert state["current_question"]["field"] != "data" or state["current_question"]["requirement_id"] != "source"
    before = copy.deepcopy(project)
    c.skip_question(project, "leave-checkpoint-open")
    assert project == before


def test_retired_source_cannot_remain_in_checkpoint_proposal():
    state = kernel_project()["conversation"]
    state["_superseded_evidence"] = [OLD]
    c._checkpoint(state, "data", readiness.REQUIREMENTS["data"][0])
    assert "proposed_answer" not in state["scope_checkpoint"]


def test_validated_reply_reassesses_saved_unprocessed_answers(monkeypatch):
    project = kernel_project(); state = project["conversation"]
    earlier = state["messages"][1]
    state["_unprocessed"] = [{"message_id": earlier["id"], "text": earlier["content"]}]
    text = "The reference outcome is measured by an approved numerical solver."
    response = scope([update("data", text)], "data", "Who can approve data reuse?",
        [requirement("data", "outcomes", text)])
    response.update(question_requirement_id="permission", question_why="Participants need permission to reuse the data.")
    calls = provider(monkeypatch, [response])
    c.submit_message(project, text, "review-saved-replies")
    import json
    context = json.loads(calls[0]["input"])
    assert any(e["message_id"] == earlier["id"] for e in context["saved_answers_to_reassess"])
    assert state["_unprocessed"] == []
    assert state["status"] == "idle"


def test_failed_reassessment_keeps_all_unprocessed_answers(monkeypatch):
    project = kernel_project(); state = project["conversation"]
    earlier = state["messages"][1]
    state["_unprocessed"] = [{"message_id": earlier["id"], "text": earlier["content"]}]
    provider(monkeypatch, [TimeoutError("Test transport interruption")])
    c.submit_message(project, "A further researcher answer.", "failed-reassessment")
    assert state["status"] == "error"
    assert len(state["_unprocessed"]) == 2
    assert state["_unprocessed"][0]["message_id"] == earlier["id"]


@pytest.mark.parametrize("email", ["", "private-organizer@example.org"])
def test_model_knows_contact_status_without_receiving_the_address(tmp_path, email):
    from autokaggle import onboarding_setup
    from autokaggle.store import Store
    import json
    project = Store(tmp_path).create("fixture-owner", "Private contact status")
    onboarding_setup.update(project, {"organizer_email": email})
    context = c._platform_context(project)
    assert context["organizer_contact_recorded"] is bool(email)
    assert "organizer_email" not in context["organizer_settings"]
    if email:
        assert email not in json.dumps(context)


@pytest.mark.parametrize("field,criterion,text,setting,value", [
    ("competition", "choice", "Competition: prediction", "competition_type", "prediction"),
    ("competition", "choice", "Competition: code", "competition_type", "code"),
    ("submissions", "allowance", "Daily submissions: 5", "daily_submission_limit", 5),
    ("submissions", "allowance", "Daily submissions: 12", "daily_submission_limit", 12),
])
def test_required_setting_checkpoint_accepts_valid_choice_and_advances(monkeypatch, field, criterion, text, setting, value):
    project = kernel_project(); state = project["conversation"]
    state["_interview_round"] = 5
    project["_model_calls"] = 41
    state["_interview_call_start"] = 40
    state["_criterion_asks"][field + "." + criterion] = 2
    state["scope_checkpoint"] = None
    c._checkpoint(state, field, readiness.REQUIREMENTS[field][0])
    before = c.conversation_view(project)
    assert before["interview"]["current_stage"] == "setup"
    assert next(item for item in before["checklist"] if item["id"] == field)["active"]
    assert not next(item for item in before["checklist"] if item["id"] == field)["can_accept_scope"]
    assert "cannot be resolved through scope acceptance" in state["messages"][-1]["content"]
    calls = provider(monkeypatch, [])
    c.submit_message(project, text, "required-setting-choice")
    assert project["setup"][setting] == value
    if field == "submissions":
        assert project["setup"]["submissions_confirmed"]
    assert state["items"][field]["status"] == "answered"
    assert state["status"] == "idle" and not calls
    active = state["current_question"] or state.get("scope_checkpoint")
    assert active is None or active["field"] != field
    assert not any(m["content"] == "Skip this question." for m in state["messages"])
    saved = copy.deepcopy(project)
    c.submit_message(project, text, "required-setting-choice")
    assert project == saved


@pytest.mark.parametrize("orphan", [{"_inflight": True}, {"status": "working"}])
def test_reopening_orphaned_request_exposes_retry_without_restart(tmp_path, monkeypatch, orphan):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    monkeypatch.setenv("AUTOKAGGLE_PRIVATE_MODE", "0")
    app = create_app(tmp_path)
    try:
        with TestClient(app) as client:
            identifier = client.post("/api/projects", json={"title": "Recoverable request"}).json()["id"]
            item = app.state.store.get(identifier, client.cookies["autokaggle_owner"])
            state = c.ensure_conversation(item)
            state.update(orphan, _pending={"kind": "message", "text": "Predict stability.", "message_id": "saved", "field": None, "was_draft": False})
            app.state.store.save(item)
            lock = app.state.store.lock(identifier)
            with lock:
                assert client.get(f"/api/projects/{identifier}/conversation").json()["status"] == "working"
                assert app.state.store.get(identifier, client.cookies["autokaggle_owner"])["conversation"].get("_inflight") == state.get("_inflight")
            view = client.get(f"/api/projects/{identifier}/conversation").json()
            assert view["status"] == "error" and view["can_retry"]
            assert "interrupted" in view["error"]
            assert client.get(f"/api/projects/{identifier}/conversation").json() == view
    finally:
        app.state.pool.shutdown(wait=True)
