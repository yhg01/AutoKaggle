"""Response recovery preserves evidence, state, budgets, and retry identity."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from autokaggle import conversation as c
from autokaggle.store import public_project
from autokaggle.tests.test_conversation import draft, provider, requirement, scope, update


@pytest.fixture
def project():
    return {"title": "New challenge", "answers": {}, "_model_calls": 0}


def good_scope(text="Predict stability."):
    return {**scope([update("question", text)], "task", "Which inputs are available?",
                    [requirement("question", "scope", text)]),
            "question_requirement_id": "inputs", "question_why": "An attempt needs defined inputs."}


@pytest.mark.parametrize("presentation", [
    {"question_text": "Please describe " + "the available planetary data " * 25},
    {"question_requirement_id": "task.inputs"},
    {"question_requirement_id": "not_a_criterion"},
    {"question_requirement_id": ""},
    {"question_field": ["task"]},
    {"question_text": ""},
    {"question_text": None},
    {"question_why": "x" * 1001},
    {"question_why": []},
    {"question_why": ""},
    {"question_text": "Which inputs? Which labels?"},
])
def test_question_defect_uses_one_call_and_keeps_valid_facts(monkeypatch, project, presentation):
    calls = provider(monkeypatch, [{**good_scope(), **presentation}])
    c.submit_message(project, "Predict stability.", "first")
    state = project["conversation"]
    assert state["status"] == "idle" and len(calls) == 1
    assert state["items"]["question"]["requirements"]["scope"]["status"] == "recorded"
    active = state["current_question"]
    assert active and active["why"] and len(active["text"]) <= 500
    assert any(criterion["id"] == active["requirement_id"]
               for criterion in c.readiness.REQUIREMENTS[active["field"]])
    assert state["_response_diagnostics"][-1]["code"] == "question_presentation_repaired"
    assert len(state["_history"]) == 1


def test_semantic_repair_reserved_before_both_calls_and_applies_once(monkeypatch, project):
    bad = good_scope()
    bad["updates"][0]["evidence"] = ["FABRICATED-PRIVATE-REPLY"]
    snapshots = []
    calls = provider(monkeypatch, [bad, good_scope()], reserve_check=lambda: (
        snapshots and snapshots[-1]["conversation"]["items"]["question"]["value"] == "") or pytest.fail("Partial fact applied"))
    c.submit_message(project, "Predict stability.", "first", reserve=lambda p: snapshots.append(copy.deepcopy(p)))
    state = project["conversation"]
    assert state["status"] == "idle" and len(calls) == 2
    # Diagnostic snapshots surround each provider call; the budget still rises once.
    assert list(dict.fromkeys(snapshot["_model_calls"] for snapshot in snapshots)) == [1, 2]
    assert all(snapshot["conversation"]["_inflight"] for snapshot in snapshots)
    feedback = json.loads(calls[1]["input"])["response_repair"]
    assert feedback["code"] == "evidence_was_not_in_the_current_user_message"
    assert "FABRICATED" not in json.dumps(public_project(project)) + calls[1]["input"]
    assert "FABRICATED" in project["_model_traces"][0]["output"]
    assert len(state["_history"]) == 1 and len(state["items"]["question"]["evidence"]) == 1
    assert "_last_response_failure" not in state
    before = copy.deepcopy(project)
    c.submit_message(project, "Predict stability.", "first")
    assert project == before and len(calls) == 2


def test_repeated_failure_stays_atomic_and_manual_retry_gets_feedback(monkeypatch, project):
    bad = good_scope()
    bad["requirements"][0]["evidence"] = ["FABRICATED-PRIVATE-REPLY"]
    state = c.ensure_conversation(project)
    original = copy.deepcopy(state["items"])
    calls = provider(monkeypatch, [bad, bad, good_scope()])
    c.submit_message(project, "Predict stability.", "first")
    assert state["items"] == original and state["status"] == "error"
    assert len(calls) == 2 and len(state["_response_diagnostics"]) == 2
    assert "recorded evidence" in state["error"] and "ValueError" not in state["error"]
    assert "FABRICATED" not in json.dumps(public_project(project))
    assert "FABRICATED" in project["_model_traces"][0]["output"]
    c.submit_message(project, "Predict stability.", "first")
    assert len(calls) == 2
    c.retry_turn(project, "manual-retry")
    assert state["status"] == "idle" and "error_code" not in state
    assert json.loads(calls[2]["input"])["response_repair"]["code"] == "requirement_evidence_was_not_in_the_recorded_research_statements"
    saved = copy.deepcopy(project)
    c.retry_turn(project, "manual-retry")
    assert project == saved and len(calls) == 3
    assert len([m for m in state["messages"] if m["role"] == "user"]) == 1


@pytest.mark.parametrize("invalid,code", [
    ("{invalid JSON", "invalid_json_response"),
    (SimpleNamespace(status="incomplete", output_text="{}"), "incomplete_model_response"),
    (SimpleNamespace(status="completed", output_text=""), "incomplete_model_response"),
    ([], "invalid_conversation_response"),
])
def test_incomplete_or_invalid_json_receives_bounded_repair(monkeypatch, project, invalid, code):
    calls = provider(monkeypatch, [invalid, good_scope()])
    c.submit_message(project, "Predict stability.", "first")
    assert project["conversation"]["status"] == "idle" and len(calls) == 2
    assert json.loads(calls[1]["input"])["response_repair"]["code"] == code


@pytest.mark.parametrize("error", [RuntimeError("private provider detail"), TimeoutError("timeout"),
                                   OSError("network unavailable"), ValueError("provider setup failure")])
def test_provider_failures_do_not_trigger_semantic_repair(monkeypatch, project, error):
    calls = provider(monkeypatch, [error])
    c.submit_message(project, "Predict stability.", "first")
    state = project["conversation"]
    assert len(calls) == 1 and state["status"] == "error"
    assert state["error_code"] == "model_service_failure"
    assert not state.get("_response_diagnostics") and not state.get("_last_response_failure")
    assert "private provider detail" not in json.dumps(project)


def test_final_call_cannot_trigger_an_automatic_repair(monkeypatch, project):
    project["_model_calls"] = 11
    calls = provider(monkeypatch, ["not JSON"])
    c.submit_message(project, "Predict stability.", "first")
    state = project["conversation"]
    assert len(calls) == 1 and project["_model_calls"] == 12
    assert not state["can_retry"] and state["error_code"] == "invalid_json_response"
    assert state["items"]["question"]["value"] == ""
    with pytest.raises(ValueError, match="12-call"):
        c.retry_turn(project, "retry")


def test_repair_can_use_final_available_call(monkeypatch, project):
    project["_model_calls"] = 10
    calls = provider(monkeypatch, ["not JSON", good_scope()])
    c.submit_message(project, "Predict stability.", "first")
    assert len(calls) == 2 and project["_model_calls"] == 12
    assert project["conversation"]["status"] == "idle"


def test_repaired_correction_preserves_unrelated_facts(monkeypatch, project):
    state = c.ensure_conversation(project)
    state["items"]["plan"].update(value="Compute costs $20. Tokens cost $5.", status="partial")
    state["items"]["plan"]["requirements"] = {
        "compute_budget": {"status": "recorded", "value": "Compute costs $20.", "evidence": ["Compute costs $20."], "reason": ""},
        "token_budget": {"status": "recorded", "value": "Tokens cost $5.", "evidence": ["Tokens cost $5."], "reason": ""}}
    invalid = scope([update("plan", "$50", "partial", "The owner is still unknown.", "correct", ["$20 per attempt"])])
    valid = copy.deepcopy(invalid)
    valid["updates"][0]["supersedes"] = ["$20"]
    valid["requirements"] = [requirement("plan", "compute_budget", "$50")]
    calls = provider(monkeypatch, [invalid, valid])
    c.submit_message(project, "Correction: compute now costs $50.", "correct")
    assert state["status"] == "idle" and len(calls) == 2
    assert state["items"]["plan"]["value"] == "Compute costs $50. Tokens cost $5."
    assert state["items"]["plan"]["requirements"]["token_budget"]["status"] == "recorded"
    assert state["_superseded_evidence"] == ["$20"] and len(state["_history"]) == 1


def test_duplicate_assessments_require_model_repair(monkeypatch, project):
    invalid = good_scope()
    invalid["requirements"] *= 2
    calls = provider(monkeypatch, [invalid, good_scope()])
    c.submit_message(project, "Predict stability.", "first")
    assert len(calls) == 2 and project["conversation"]["status"] == "idle"
    assert json.loads(calls[1]["input"])["response_repair"]["code"] == "duplicate_requirement_assessment"


def test_no_second_automatic_repair_when_same_turn_enters_draft(monkeypatch, project):
    state = c.ensure_conversation(project)
    state["followups"] = c.MAX_FOLLOWUPS
    calls = provider(monkeypatch, ["not JSON", good_scope(), {"wrong": "draft"}])
    c.submit_message(project, "Predict stability.", "first")
    assert len(calls) == 3 and state["status"] == "error"
    assert state["error_code"] == "invalid_draft_metadata"
    assert state["readme"] and state["items"]["question"]["value"] == "Predict stability."


def test_standalone_draft_repairs_format_once(monkeypatch, project):
    calls = provider(monkeypatch, [{"title": "partial"}, draft()])
    c.make_readme(project, "draft")
    assert len(calls) == 2 and project["conversation"]["status"] == "idle"


def test_output_schema_matches_validation_bounds():
    schema = c._scope_schema()["properties"]
    assert schema["question_text"]["maxLength"] == 500
    assert schema["question_why"]["maxLength"] == 1000
    update_schema = schema["updates"]["items"]["properties"]
    assert update_schema["evidence"]["maxItems"] == 8
    assert update_schema["remaining_gap"]["maxLength"] == 1000
    assert schema["requirements"]["maxItems"] == sum(map(len, c.readiness.REQUIREMENTS.values()))
    assert c._draft_schema()["properties"]["next_actions"]["maxItems"] == 5
