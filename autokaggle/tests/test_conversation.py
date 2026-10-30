from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

import pytest

from autokaggle import conversation as c


@pytest.fixture
def project():
    return {"title": "New challenge", "brief": "Legacy brief is not a verified answer.", "answers": {"objective": "Legacy answer"}, "_model_calls": 0, "_seed": "private-seed", "dataset": {"raw_rows": "private dataset marker"}}


@pytest.fixture(autouse=True)
def rules(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")


def update(field, evidence, status="answered", gap="", operation="append", supersedes=None):
    return {"field": field, "status": status, "operation": operation, "evidence": evidence if isinstance(evidence, list) else [evidence], "supersedes": supersedes or [], "remaining_gap": gap}


def scope(updates=None, field="", question="", requirements=None):
    result = {"updates": updates or [], "question_field": field, "question_text": question}
    if requirements is not None:
        result["requirements"] = requirements
    return result


def requirement(field, identifier, evidence, status="recorded", reason=""):
    return {"field": field, "id": identifier, "status": status,
            "evidence": evidence if isinstance(evidence, list) else [evidence], "reason": reason}


def recorded_requirement(evidence, status="recorded", reason=""):
    return {"status": status, "value": evidence, "evidence": [evidence], "reason": reason}


def test_requirement_bypass_add_edit_remove_and_replay_preserve_underlying_answer(project):
    state = c.ensure_conversation(project)
    state["items"]["question"].update(value="The outcome threshold remains uncertain.", status="partial")
    before = copy.deepcopy(state["items"]["question"])
    first = c.set_requirement_bypass(project, "question", "success", "Pilot results will define the threshold.", "bypass-1")
    criterion = next(item for item in first["checklist"] if item["id"] == "question")["requirements"][2]
    assert criterion["status"] == "bypassed" and criterion["can_bypass"]
    assert criterion["bypass"]["reason"] == "Pilot results will define the threshold."
    assert first["readiness"]["bypassed"] == 1
    assert first["interview"]["stages"][0]["understanding"]["bypassed"] == 1
    assert state["items"]["question"]["value"] == before["value"]
    snapshot = copy.deepcopy(project)
    c.set_requirement_bypass(project, "question", "success", "Pilot results will define the threshold.", "bypass-1")
    assert project == snapshot
    created = state["items"]["question"]["bypasses"]["success"]["created_at"]
    c.set_requirement_bypass(project, "question", "success", "We accept an exploratory first round.", "bypass-2")
    assert state["items"]["question"]["bypasses"]["success"]["created_at"] == created
    assert len(state["_bypass_audit"]) == 2
    removed = c.set_requirement_bypass(project, "question", "success", "", "bypass-3", remove=True)
    assert removed["readiness"]["bypassed"] == 0
    assert state["items"]["question"]["value"] == before["value"]
    assert [entry["action"] for entry in state["_bypass_audit"]] == ["add", "update", "remove"]
    with pytest.raises(ValueError, match="different action"):
        c.set_requirement_bypass(project, "question", "success", "Different reason.", "bypass-1")


@pytest.mark.parametrize("reason", ["", "   ", None, 42, "x" * 2001])
def test_requirement_bypass_rejects_invalid_reason_without_mutation(project, reason):
    c.ensure_conversation(project)
    before = copy.deepcopy(project)
    with pytest.raises(ValueError, match="bypass reason"):
        c.set_requirement_bypass(project, "question", "success", reason, "invalid-bypass")
    assert project == before


@pytest.mark.parametrize("field,identifier", [("organizer", "contact"), ("competition", "choice"),
                                          ("submissions", "allowance"), ("trial", "execution"),
                                          ("difficulty", "reference"), ("question", "invented")])
def test_requirement_bypass_rejects_nonmanual_requirements(project, field, identifier):
    c.ensure_conversation(project)
    before = copy.deepcopy(project)
    with pytest.raises(ValueError, match="cannot be bypassed"):
        c.set_requirement_bypass(project, field, identifier, "A reason.", "invalid-field")
    assert project == before


@pytest.mark.parametrize("busy", [{"status": "working"}, {"status": "error"}, {"_pending": {"kind": "draft"}},
                                 {"_inflight": True}, {"_unprocessed": [{"text": "A new correction."}]}])
def test_requirement_bypass_waits_for_existing_answers(project, busy):
    state = c.ensure_conversation(project)
    state.update(busy)
    before = copy.deepcopy(project)
    with pytest.raises(ValueError, match="Finish or retry"):
        c.set_requirement_bypass(project, "question", "success", "A reason.", "busy-bypass")
    assert project == before


def test_bypass_replaces_its_active_question_without_model_call(monkeypatch, project):
    state = c.ensure_conversation(project)
    state.update(phase="conversation", current_question={"field": "question", "text": "What success threshold should apply?"})
    state["items"]["question"]["requirements"] = {
        "scope": recorded_requirement("Predict the survival of synthetic organisms."),
        "value": recorded_requirement("We seek to reduce the number of expensive experiments.")}
    calls = provider(monkeypatch, [])
    result = c.set_requirement_bypass(project, "question", "success", "The first round estimates a threshold.", "active-bypass")
    assert not calls and project["_model_calls"] == 0
    assert result["current_question"]["field"] == "task"
    assert result["checklist"][0]["understanding"]["score"] == 100
    assert "success threshold" not in result["current_question"]["text"].lower()


def test_data_source_bypass_does_not_add_another_source_link_request(project):
    state = c.ensure_conversation(project)
    state.update(phase="conversation", current_question={"field": "data", "text": "Which dataset link can you share?"})
    view = c.set_requirement_bypass(project, "data", "source", "The dataset will be supplied under a separate agreement.", "source-bypass")
    assert view["current_question"]["field"] == "data"
    assert "labels or outcomes" in view["current_question"]["text"]
    assert "Google Drive" not in view["current_question"]["text"]
    assert "Please share a link" not in view["current_question"]["text"]


def test_bypass_reaches_complete_definition_without_automatic_draft(monkeypatch, project):
    from autokaggle.tests.readiness_fixtures import complete_definition
    c.onboarding_setup.update(project, {"organizer_email": "organizer@example.org", "competition_type": "prediction",
                                        "submissions_confirmed": True}, source="form")
    complete_definition(project)
    state = c.ensure_conversation(project)
    state["items"]["question"]["requirements"].pop("success")
    state.update(phase="conversation", current_question={"field": "question", "text": "What result is useful?"})
    calls = provider(monkeypatch, [])
    result = c.set_requirement_bypass(project, "question", "success", "The first trial determines useful progress.", "last-bypass")
    assert result["readiness"]["ready"] and result["readiness"]["bypassed"] == 1
    assert result["current_question"] is None
    assert result["interview"]["can_draft"]
    assert not result["readme"] and not calls


def test_model_assessments_and_corrections_cannot_remove_manual_bypass(project):
    state = c.ensure_conversation(project)
    state["items"]["plan"].update(value="Compute costs $20.", status="partial")
    c.set_requirement_bypass(project, "plan", "compute_budget", "The team will provide shared compute.", "compute-bypass")
    original = copy.deepcopy(state["items"]["plan"]["bypasses"])
    c._apply(state, [update("plan", "$50", "partial", "Other budget details remain.", "correct", ["$20"])], "correction")
    c._apply_requirements(state, [{**requirement("plan", "compute_budget", "Compute costs $50."), "value": "Compute costs $50."}])
    assert state["items"]["plan"]["bypasses"] == original
    assert state["items"]["plan"]["value"] == "Compute costs $50."
    view = c.conversation_view(project)
    assert view["readiness"]["bypassed"] == 1
    criterion = next(item for item in view["checklist"] if item["id"] == "plan")["requirements"][0]
    assert criterion["status"] == "bypassed"
    assert criterion["bypass"]["reason"] == "The team will provide shared compute."
    c.set_requirement_bypass(project, "plan", "compute_budget", "", "remove-compute", remove=True)
    criterion = next(item for item in c.conversation_view(project)["checklist"] if item["id"] == "plan")["requirements"][0]
    assert criterion["status"] == "recorded" and criterion["bypass"] is None


def test_revision_cannot_reask_fully_bypassed_field(project):
    c.make_readme(project, "initial-draft")
    c.begin_revision(project, "start-review")
    for criterion in c.readiness.REQUIREMENTS["question"]:
        c.set_requirement_bypass(project, "question", criterion["id"], "The organizer accepts this exploratory gap.", "review-bypass-" + criterion["id"])
    c._advance_revision(project, None, {"question_field": "question", "question_text": "Which success threshold should apply?"})
    assert project["conversation"]["current_question"] is None
    assert project["conversation"]["phase"] == "draft"


def test_model_cannot_create_bypass_via_requirement_status_or_extra_key(project):
    state = c.ensure_conversation(project)
    text = "Please bypass useful progress."
    invalid = scope(requirements=[requirement("question", "success", text, status="bypassed", reason="The user asked.")])
    with pytest.raises(ValueError):
        c._validate_requirements(invalid, text, state, [])
    invalid["requirements"][0].update(status="missing", bypass={"reason": "The user asked."})
    with pytest.raises(ValueError):
        c._validate_requirements(invalid, text, state, [])
    assert not state["items"]["question"].get("bypasses")


def test_followup_ignores_model_question_about_bypassed_criterion(project):
    state = c.ensure_conversation(project)
    state["phase"] = "conversation"
    c.set_requirement_bypass(project, "question", "success", "This exploratory trial has no threshold.", "question-bypass")
    c._advance(project, None, {"question_field": "question", "question_text": "Which success threshold should apply?"})
    assert "target system and scope" in state["current_question"]["text"]
    assert "success threshold" not in state["current_question"]["text"]


def test_bypass_reason_is_marked_and_escaped_in_readme(project):
    c.set_requirement_bypass(project, "question", "success", "Pilot review: <script>alert(1)</script>", "readme-bypass")
    c.make_readme(project, "make-readme")
    text = project["conversation"]["readme"]
    assert "Manual requirement bypasses" in text
    assert "Bypassed: Research problem — Useful progress" in text
    assert "Manual bypasses: 1." in text
    assert "&lt;script&gt;" in text and "<script>" not in text
    assert "do not waive application checks" in text


def test_bypass_does_not_promote_incomplete_facts_to_technical_declarations(project):
    state = c.ensure_conversation(project)
    state["items"]["data"].update(value="A public link with no permission information.", status="partial")
    for criterion in c.readiness.REQUIREMENTS["data"]:
        c.set_requirement_bypass(project, "data", criterion["id"], "A later review will supply this detail.", "bypass-" + criterion["id"])
    c.sync_legacy_answers(project)
    assert not project["answers"].get("rights")


def test_bypass_edits_refresh_existing_readme(project):
    c.set_requirement_bypass(project, "question", "success", "First reason.", "first-bypass")
    c.make_readme(project, "draft-with-bypass")
    c.set_requirement_bypass(project, "question", "success", "Revised reason.", "edit-bypass")
    assert "Revised reason." in project["conversation"]["readme"]
    assert "First reason." not in project["conversation"]["readme"]
    c.set_requirement_bypass(project, "question", "success", "", "remove-bypass", remove=True)
    assert "Manual requirement bypasses" not in project["conversation"]["readme"]
    assert "Open: Useful progress" in project["conversation"]["readme"]


def draft(title="A scoped research challenge"):
    return {"title": title, "intro": "A draft based on the recorded research description.", "next_actions": ["Review the unresolved decisions with the scientist."]}


def provider(monkeypatch, outputs, reserve_check=None):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "model")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-tests")
    queue, calls = list(outputs), []

    class Fake:
        def __init__(self, **_kwargs):
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def create(self, **kwargs):
            calls.append(kwargs)
            if reserve_check:
                reserve_check()
            if not queue:
                raise AssertionError("Unexpected provider call")
            answer = queue.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            if isinstance(answer, SimpleNamespace):
                return answer
            return SimpleNamespace(status="completed", output_text=answer if isinstance(answer, str) else json.dumps(answer))

    import openai
    monkeypatch.setattr(openai, "OpenAI", Fake)
    return calls


def users(state):
    return [message for message in state["messages"] if message["role"] == "user"]


def test_initial_view_has_three_interview_stages_without_legacy_fill(project):
    state = c.ensure_conversation(project)
    view = c.conversation_view(project)
    assert len(view["checklist"]) == 17
    assert list(dict.fromkeys(item["pillar"] for item in view["checklist"])) == c.PILLARS
    assert all(item["status"] == "missing" for item in view["checklist"])
    assert view["phase"] == "initial" and view["current_question"] is None
    assert len(view["messages"]) == 1 and view["messages"][0]["role"] == "assistant"
    assert not any(key.startswith("_") for key in view)
    assert "private-seed" not in json.dumps(view)
    assert c.ensure_conversation(project) is state
    view["messages"].clear()
    assert state["messages"]
    assert [stage["id"] for stage in view["interview"]["stages"]] == ["problem", "approach", "baseline"]
    assert view["interview"]["current_stage"] == "problem"
    assert view["interview"]["next_question"] == c.INITIAL_MESSAGE
    assert view["interview"]["next_question"].count("?") <= 1
    assert all("trial" not in stage["fields"] for stage in view["interview"]["stages"])


@pytest.mark.parametrize("status,value,score", [
    ("missing", "", 0),
    ("missing", "Our data contains battery cycles.", 0),
    ("partial", "", 0),
    ("partial", "Our data contains battery cycles.", 0),
    ("answered", "", 0),
    ("answered", "  \n ", 0),
    ("answered", "Our data contains battery cycles.", 0),
    ("deferred", "", 0),
    ("deferred", "Our data contains battery cycles.\nI don't know", 0),
    ("deferred", "Unknown\nOur data contains battery cycles.", 0),
    ("deferred", "The best known method is X but its score is unknown", 0),
    ("partial", "I do not know which reference method to use. We have 100 batteries.", 0),
    ("deferred", "The score is not known yet; the code is available in our repository.", 0),
])
def test_understanding_requires_recorded_facts_and_respects_item_status(project, status, value, score):
    state = c.ensure_conversation(project)
    state["items"]["data"].update(status=status, value=value)
    view = c.conversation_view(project)
    item = next(item for item in view["checklist"] if item["id"] == "data")
    assert item["understanding"]["score"] == score
    assert item["owner"] == "researcher"
    assert item["status"] == status and item["value"] == value
    assert item["understanding"]["label"] and item["understanding"]["detail"]


@pytest.mark.parametrize("value", ["unknown", "I don't know.", "I don’t know yet", "not sure yet",
                                  "Skip this question.", "TBD", "n/a", "?", "\nunknown\nSkip\n",
                                  "Data: unknown", "Data or environment: not sure", "Unknown task",
                                  "The reference method is unknown.", "I don't know the baseline.",
                                  "I do not know which reference method to use", "The reference method is not known yet",
                                  "Not yet known", "Not yet decided", "Undecided", "We are not sure which data to use.",
                                  "Methodology: I haven't decided which method to use.",
                                  "The baseline is undecided for now.", "Unknown. I do not know the reference method."])
@pytest.mark.parametrize("status", ["answered", "partial", "deferred"])
def test_unknown_only_answers_do_not_fill_understanding_bars(project, status, value):
    state = c.ensure_conversation(project)
    state["items"]["data"].update(status=status, value=value)
    item = next(item for item in c.conversation_view(project)["checklist"] if item["id"] == "data")
    assert item["understanding"]["score"] == 0


def test_old_recorded_values_remain_visible_but_do_not_complete_unassessed_requirements(project):
    state = c.ensure_conversation(project)
    state["items"]["question"] = {"status": "answered", "value": "Predict battery life from cycle data.", "gap": ""}
    before = copy.deepcopy(state)
    view = c.conversation_view(project)
    item = next(item for item in view["checklist"] if item["id"] == "question")
    assert item["understanding"]["score"] == 0
    assert item["value"] == "Predict battery life from cycle data."
    assert item["understanding"]["completed"] == 0
    assert state == before


def test_topic_understanding_counts_requirements_and_keeps_trial_separate(project):
    state = c.ensure_conversation(project)
    state["items"]["question"].update(status="answered", value="Predict battery life.")
    state["items"]["task"].update(status="partial", value="Input is cycle data.")
    state["items"]["methodology"].update(status="partial", value="Neural networks are allowed.")
    state["items"]["difficulty"].update(status="answered", value="Compare against a random forest.")
    state["items"]["trial"].update(status="answered", value="Researcher says it ran.")
    state["items"]["question"]["requirements"] = {"scope": recorded_requirement("Predict battery life.")}
    state["items"]["task"]["requirements"] = {"inputs": recorded_requirement("Input is cycle data.")}
    state["items"]["methodology"]["requirements"] = {"methods": recorded_requirement("Neural networks are allowed.")}
    state["items"]["difficulty"]["requirements"] = {"reference": recorded_requirement("Compare against a random forest.")}
    view = c.conversation_view(project)
    assert {stage["id"]: stage["understanding"]["score"] for stage in view["interview"]["stages"]} == {
        "problem": 12, "approach": 12, "baseline": 33,
    }
    trial = next(item for item in view["checklist"] if item["id"] == "trial")
    assert trial["owner"] == "agent" and not trial["active"]
    assert trial["understanding"]["score"] is None
    assert trial["understanding"]["label"] == "Optional system check"
    assert "scientific truth" in view["interview"]["understanding_note"]
    assert "completed execution" in view["interview"]["understanding_note"]


def test_correction_can_reduce_understanding_without_discarding_other_facts(monkeypatch, project):
    first = "Predict battery life. We have 100 batteries with lifetime labels."
    correction = "Correction: labels are not available yet."
    provider(monkeypatch, [
        scope([update("question", "Predict battery life."), update("data", "We have 100 batteries with lifetime labels.")], "task", "What should a solution produce?", requirements=[
            requirement("question", "scope", "Predict battery life."), requirement("data", "outcomes", "We have 100 batteries with lifetime labels.")]),
        scope([update("data", "labels are not available yet.", "partial", "Which labels will be available?", "correct", ["with lifetime labels."])], "methodology", "Which methods can participants use?", requirements=[]),
    ])
    c.submit_message(project, first, "brief")
    before = c.conversation_view(project)
    assert next(item for item in before["checklist"] if item["id"] == "data")["understanding"]["score"] == 33
    c.submit_message(project, correction, "correction")
    after = c.conversation_view(project)
    data = next(item for item in after["checklist"] if item["id"] == "data")
    assert data["understanding"]["score"] == 0
    assert "100 batteries" in data["value"] and "labels are not available yet" in data["value"]
    assert next(item for item in after["checklist"] if item["id"] == "question")["understanding"]["score"] == 33


def test_active_item_moves_with_the_interview_and_skip_is_not_knowledge(project):
    initial = c.conversation_view(project)
    assert [item["id"] for item in initial["checklist"] if item["active"]] == ["question"]
    c.submit_message(project, "Predict battery life.", "brief")
    view = c.conversation_view(project)
    active = view["current_question"]["field"]
    assert [item["id"] for item in view["checklist"] if item["active"]] == [active]
    c.skip_question(project, "skip")
    view = c.conversation_view(project)
    skipped = next(item for item in view["checklist"] if item["id"] == active)
    assert not skipped["active"] and skipped["status"] == "deferred"
    assert skipped["understanding"]["score"] == 0


@pytest.mark.parametrize("text,request_id", [("", "id"), ("   ", "id"), ("x" * 12001, "id"), (None, "id"), ("hello", ""), ("hello", []), ("hello", "x" * 101)])
def test_invalid_input_does_not_append_messages(project, text, request_id):
    state = c.ensure_conversation(project)
    with pytest.raises(ValueError):
        c.submit_message(project, text, request_id)
    assert len(state["messages"]) == 1
    assert state["_requests"] == {}


@pytest.mark.parametrize("previous", sorted(c.PREVIOUS_INITIAL_MESSAGES))
def test_refreshes_untouched_opening_without_changing_message_identity(project, previous):
    state = c.ensure_conversation(project)
    state["messages"][0]["content"] = previous
    original_id = state["messages"][0]["id"]
    view = c.conversation_view(project)
    assert view["messages"] == [{"id": original_id, "role": "assistant", "content": c.INITIAL_MESSAGE}]
    assert all(item["status"] == "missing" for item in view["checklist"])


def test_preserves_opening_after_researcher_has_replied(project):
    state = c.ensure_conversation(project)
    previous = sorted(c.PREVIOUS_INITIAL_MESSAGES)[0]
    state["messages"][0]["content"] = previous
    state["messages"].append({"id": "researcher-reply", "role": "user", "content": "Study material stability."})
    assert c.conversation_view(project)["messages"][0]["content"] == previous


@pytest.mark.parametrize("field,value", [("_pending", {"action": "scope"}), ("_inflight", True), ("current_question", {"field": "task", "text": "What should it produce?"})])
def test_preserves_opening_while_interview_work_is_pending(project, field, value):
    state = c.ensure_conversation(project)
    previous = sorted(c.PREVIOUS_INITIAL_MESSAGES)[0]
    state["messages"][0]["content"] = previous
    state[field] = value
    assert c.conversation_view(project)["messages"][0]["content"] == previous


def test_rules_mode_is_explicit_and_does_not_claim_complete_extraction(project):
    c.submit_message(project, "Predict catalyst performance using our observations.", "first")
    state = c.ensure_conversation(project)
    assert state["items"]["question"]["status"] == "partial"
    assert state["items"]["question"]["value"] == "Predict catalyst performance using our observations."
    assert state["current_question"]["field"] == "task"
    assert any("Rules mode" in message["content"] for message in state["messages"])
    assert project["_model_calls"] == 0


def test_model_extracts_multiple_items_once_and_asks_one_missing_question(monkeypatch, project):
    text = "Predict stability. Input is temperature; output is stable. Use balanced accuracy."
    calls = provider(monkeypatch, [scope([update("question", "Predict stability."), update("task", "Input is temperature; output is stable. Use balanced accuracy.")], "data", "What permission applies to the data?")])
    c.submit_message(project, text, "first")
    state = c.ensure_conversation(project)
    assert state["items"]["question"]["status"] == state["items"]["task"]["status"] == "answered"
    assert state["current_question"]["field"] == "data"
    assert state["current_question"]["text"] == "What permission applies to the data? " + c.DATA_LINK_GUIDANCE
    assert state["current_question"]["requirement_id"] and state["current_question"]["why"]
    assert state["followups"] == 1
    assert calls[0]["reasoning"] == {"effort": "medium"}
    assert "private dataset marker" not in calls[0]["input"]
    assert "private-seed" not in calls[0]["input"]
    assert "tools" not in calls[0]


@pytest.mark.parametrize("question", ["Which simulation dataset provides the stability labels?", "Please upload the full dataset."])
def test_model_data_question_requests_a_shareable_link(monkeypatch, project, question):
    provider(monkeypatch, [scope([], "data", question)])
    c.submit_message(project, "We have a large set of planetary simulations.", "data-link")
    text = c.conversation_view(project)["current_question"]["text"]
    assert '"Anyone with the link"' in text and "Viewer" in text and "Google Drive" in text
    assert "Please upload" not in text
    assert c.CSV_UPLOAD_GUIDANCE in text


def test_supplied_dataset_link_is_preserved_without_another_source_request(monkeypatch, project):
    text = "Dataset: https://example.org/planetary-simulations.csv. Labels come from long integrations."
    question = "What permission applies to this dataset?"
    provider(monkeypatch, [scope([update("data", text, "partial", "Permission is unknown.")], "data", question)])
    c.submit_message(project, text, "provided-link")
    state = c.ensure_conversation(project)
    assert state["current_question"]["text"] == question
    assert state["items"]["data"]["value"] == text


@pytest.mark.parametrize("question", [
    "Which simulation dataset provides the labels?",
    'Which simulation dataset provides the labels? A Google Drive link set to “Anyone with the link” and “Viewer” is standard; a direct dataset or repository URL also works.',
    'Which simulation dataset provides the labels? ' + c.DATA_LINK_GUIDANCE,
    'Which simulation dataset provides the labels? Please share a Google Drive link set to "Anyone with the link" with Viewer access. Use a link instead of uploading the full dataset.',
])
def test_pending_dataset_question_refresh_preserves_history_and_question_count(project, question):
    state = c.ensure_conversation(project)
    c._message(state, "user", "Predict stability without long integrations.")
    c._message(state, "assistant", "What duration defines stability?")
    c._message(state, "user", "Several Gyr without collisions or ejections.")
    c._message(state, "assistant", question)
    state.update(phase="conversation", followups=2, current_question={"field": "data", "text": state["messages"][-1]["content"]})
    state["_asked_questions"] = [re.sub(r"\W+", " ", question.lower()).strip()]
    before = copy.deepcopy(state)
    view = c.conversation_view(project)
    assert view["messages"][:-1] == before["messages"][:-1]
    assert view["messages"][-1]["id"] == before["messages"][-1]["id"]
    assert view["messages"][-1]["content"] == view["current_question"]["text"]
    assert "Google Drive" in view["current_question"]["text"] and view["followups"] == 2
    assert view["current_question"]["text"].startswith("Which simulation dataset provides the labels?")
    assert view["current_question"]["text"].count(c.CSV_UPLOAD_GUIDANCE) == 1
    assert "instead of uploading" not in view["current_question"]["text"]
    assert state["_asked_questions"] == [re.sub(r"\W+", " ", view["current_question"]["text"].lower()).strip()]
    assert c.conversation_view(project) == view


@pytest.mark.parametrize("guard", ["_pending", "_inflight", "answered", "error"])
def test_data_question_refresh_leaves_active_or_answered_exchanges_unchanged(project, guard):
    state = c.ensure_conversation(project)
    c._message(state, "assistant", "Which data is available?")
    state.update(phase="conversation", current_question={"field": "data", "text": state["messages"][-1]["content"]})
    if guard == "answered":
        c._message(state, "user", "The dataset link is unavailable.")
    elif guard == "error":
        state["status"] = "error"
    else:
        state[guard] = True
    before = copy.deepcopy(state)
    c.ensure_conversation(project)
    assert state == before


def test_rules_mode_requests_data_link_and_defers_unknown_source(project):
    c.submit_message(project, "Predict planetary stability.", "problem")
    c.submit_message(project, "Use orbital elements to predict stability labels.", "task")
    assert "Google Drive" in c.conversation_view(project)["current_question"]["text"]
    c.submit_message(project, "I don't know", "unknown-source")
    state = c.ensure_conversation(project)
    assert state["items"]["data"]["status"] == "deferred"
    assert state["current_question"]["field"] != "data"


def test_model_receives_fixed_platform_contract_without_changing_researcher_evidence(monkeypatch, project):
    c.onboarding_setup.update(project, {"competition_type": "code", "organizer_email": "private-owner@example.org"})
    text = "Predict stability from temperature."
    calls = provider(monkeypatch, [scope([update("question", text)], "task", "Which scientific metric should measure success?")])
    c.submit_message(project, text, "platform")
    context = json.loads(calls[0]["input"])["platform_context"]
    code = context["code_competition"]
    assert code["entrypoint"] == "python predict.py --input INPUT.csv --output predictions.csv"
    assert code["training_path"] == "/input/train.csv"
    assert context["submission"]["columns"] == ["_autokaggle_id", "prediction"]
    assert code["resources"] == {"cpu": 1, "memory_mib": 512, "cpu_seconds": 90, "program_seconds": 100, "job_seconds": 120, "gpu": 0}
    assert "standard library" in code["dependencies"]
    assert "separate trusted scorer" in code["visibility"]
    assert context["organizer_settings"]["competition_type"] == "code"
    assert "private-owner@example.org" not in json.dumps(context)
    assert "Do not ask the researcher to choose the Python command" in calls[0]["instructions"]
    assert "Do not treat them as missing researcher decisions" in calls[0]["instructions"]
    state = project["conversation"]
    assert state["items"]["question"]["value"] == text
    assert state["items"]["protocol"]["status"] == "missing"
    assert state["items"]["trial"]["status"] == "missing"


def test_twelve_scientific_updates_and_three_server_choices_fit_one_message(monkeypatch, project):
    statements = {key: f"Recorded information for {key}." for key in c.BY_ID if key not in c.onboarding_setup.ITEM_FIELDS}
    text = (" ".join(statements.values()) + " Choose code submissions, five submissions per team per UTC day. "
            "The organizer review email is private-owner@example.org.")
    calls = provider(monkeypatch, [scope([update(key, value) for key, value in statements.items()], "competition", "Which competition type?"), draft()])
    c.submit_message(project, text, "complete")
    state = project["conversation"]
    assert all(item["status"] == "answered" for key, item in state["items"].items() if key not in c.AGENT_OWNED_FIELDS)
    assert state["items"]["trial"]["status"] == "partial"
    assert state["followups"] == 0 and state["current_question"] is None
    assert state["phase"] == "draft"
    assert "private-owner@example.org" not in state["readme"]
    context = json.loads(calls[0]["input"])
    assert all(context["recorded_items"][key]["status"] == "answered" for key in c.onboarding_setup.ITEM_FIELDS)
    assert len(calls) == 2


def test_draft_context_includes_platform_rules_without_claiming_execution(monkeypatch, project):
    calls = provider(monkeypatch, [draft()])
    c.make_readme(project, "draft-platform")
    context = json.loads(calls[0]["input"])["platform_context"]
    assert "not evidence of completed work" in context["source"]
    assert "Final answers and scores stay private" in context["feedback"]
    assert "runtime acceptance pass" in context["application_work"][1]
    assert project["conversation"]["items"]["trial"]["status"] == "missing"


def test_scope_sees_saved_data_facts_without_rows_private_seed_or_final_scores(monkeypatch, project):
    project.update(dataset={"filename": "measurements.csv", "rows": 150, "size_bytes": 1234,
                            "columns": [{"name": "target", "dtype": "int64", "values": ["PRIVATE LABEL"]}],
                            "raw_rows": "PRIVATE ROW"},
                   design={"target": "target", "metric": "accuracy", "seed": "PRIVATE SEED"},
                   analysis={"baseline": {"status": "complete", "metric": "accuracy", "score": 0.6,
                                          "validation_rows": 24, "private_predictions": "PRIVATE PREDICTION"},
                             "final_score": "PRIVATE FINAL"})
    project["answers"].update(rights="confirmed", compute_budget="$25")
    calls = provider(monkeypatch, [scope([update("question", "Predict stability.")], "task", "Which output is useful?")])
    c.submit_message(project, "Predict stability.", "metadata")
    request = calls[0]["input"]
    saved = json.loads(request)["saved_project_context"]
    assert saved["dataset_metadata"]["filename"] == "measurements.csv"
    assert saved["dataset_metadata"]["columns"] == [{"name": "target", "dtype": "int64"}]
    assert saved["organizer_declarations"]["rights"] == "confirmed"
    assert saved["organizer_declarations"]["compute_budget"] == "$25"
    assert saved["development_baseline"]["score"] == 0.6
    assert "PRIVATE" not in request
    assert "Configuration can include defaults" in saved["design_note"]
    assert "not reproduction" in saved["baseline_note"]


@pytest.mark.parametrize("unknown", ["I don't know", "I do not know yet", "not sure yet", "Skip", "unknown"])
def test_unknown_defers_current_item_without_another_model_call(monkeypatch, project, unknown):
    calls = provider(monkeypatch, [scope([update("question", "Predict stability")], "data", "What data can you provide?")])
    c.submit_message(project, "Predict stability", "first")
    c.submit_message(project, unknown, "unknown")
    state = c.ensure_conversation(project)
    assert len(calls) == 1
    assert state["items"]["data"]["status"] == "deferred"
    assert state["current_question"]["field"] != "data"
    assert state["items"]["data"]["gap"]


def test_skips_are_idempotent_and_never_repeat_a_question(project):
    c.submit_message(project, "A vague research idea.", "first")
    state = c.ensure_conversation(project)
    first = state["current_question"]["field"]
    c.skip_question(project, "skip")
    snapshot = copy.deepcopy(state)
    c.skip_question(project, "skip")
    assert state == snapshot
    assert state["items"][first]["status"] == "deferred"
    assert state["current_question"]["field"] != first


def test_eight_followups_end_in_draft_with_unresolved_items(project):
    c.submit_message(project, "A research idea.", "start")
    state = c.ensure_conversation(project)
    seen = []
    for index in range(8):
        seen.append(state["current_question"]["field"])
        c.skip_question(project, f"skip-{index}")
    assert len(seen) == len(set(seen)) == 8
    assert state["followups"] == 8
    assert state["phase"] == "draft" and state["current_question"] is None
    assert "Unresolved required items" in state["readme"]
    assert "Pending organizer review" in state["readme"]
    assert all(f"### {label}" in state["readme"] for key, label, *_ in c.ITEMS if key != "organizer")
    assert "### Organizer email" not in state["readme"]


def test_draft_at_start_and_explicit_draft_message(project):
    c.make_readme(project, "draft")
    state = c.ensure_conversation(project)
    assert state["phase"] == "draft" and state["followups"] == 0
    assert state["readme"].count("No answer recorded.") == 15
    assert "5 submissions per day (default or proposed; not confirmed)" in state["readme"]
    before = len(users(state))
    c.make_readme(project, "draft")
    assert len(users(state)) == before
    other = {"title": "New challenge", "_model_calls": 0}
    c.submit_message(other, "Please create a draft README now", "draft-message")
    assert c.ensure_conversation(other)["phase"] == "draft"


def test_all_items_answered_skips_questions_and_drafts(monkeypatch, project):
    c.onboarding_setup.update(project, {"competition_type": "code", "submissions_confirmed": True, "organizer_email": "owner@example.org"})
    statements = {key: f"Recorded information for {key}." for key in c.BY_ID if key not in c.onboarding_setup.ITEM_FIELDS}
    text = " ".join(statements.values())
    calls = provider(monkeypatch, [scope([update(key, value) for key, value in statements.items()]), draft()])
    c.submit_message(project, text, "all")
    state = c.ensure_conversation(project)
    assert state["phase"] == "draft" and state["followups"] == 0
    assert all(item["status"] == "answered" for key, item in state["items"].items() if key not in c.AGENT_OWNED_FIELDS)
    assert [call["reasoning"]["effort"] for call in calls] == ["medium", "high"]
    assert "Application execution evidence is still required" in state["readme"]
    assert project["title"] == "A scoped research challenge"


def test_covered_or_deferred_items_cannot_be_asked(monkeypatch, project):
    calls = provider(monkeypatch, [scope([update("question", "Predict stability"), update("task", "Unknown task", "deferred", "Task is unknown")], "question", "What question?")])
    c.submit_message(project, "Predict stability. Unknown task", "first")
    assert c.ensure_conversation(project)["current_question"]["field"] == "data"
    assert len(calls) == 1


def test_partial_fallback_asks_only_the_recorded_gap(monkeypatch, project):
    provider(monkeypatch, [scope([update("question", "Predict stability"), update("task", "Input is temperature; output is stable", "partial", "Which metric measures useful progress?")])])
    c.submit_message(project, "Predict stability. Input is temperature; output is stable", "first")
    question = c.ensure_conversation(project)["current_question"]
    assert question["field"] == "task"
    assert "Which metric measures useful progress?" in question["text"]
    assert "What must a model predict" not in question["text"]


def test_skipping_moves_to_natural_question_for_partial_research_problem(project):
    state = c.ensure_conversation(project)
    state["items"]["question"].update(status="partial", value="Predict market returns.",
        gap="The outcome or improvement that would count as useful progress is not specified.")
    state["current_question"] = {"field": "data", "text": "Where did the data come from?"}
    state["_asked"].append("data")
    c.skip_question(project, "skip-data")
    assert state["current_question"]["field"] == "question"
    assert state["current_question"]["text"] == "What improvement would count as useful progress for this research?"


@pytest.mark.parametrize("field,gap,expected", [
    ("task", "The metric is not specified.", "Which measure would show a useful result?"),
    ("task", "The available inputs are unclear.", "Which inputs would the solution receive?"),
    ("data", "Label provenance is unclear.", "How were the labels obtained?"),
    ("data", "The source is not specified.", "Where did these data come from?"),
    ("data", "Permission is not specified.", "What permission applies to the data you described?"),
    ("deployment", "Which features arrive before the prediction? What is the runtime?", "Which features arrive before the prediction?"),
])
def test_partial_questions_are_short_and_focus_on_the_missing_detail(field, gap, expected):
    assert c._partial_question(field, gap, "Full item fallback?") == expected


def test_interviewer_extracts_method_deployment_and_reference_from_one_answer(monkeypatch, project):
    facts = {
        "question": "Reduce failed material tests.",
        "task": "Return a stability probability from temperature and composition.",
        "data": "We own the labeled measurements and permit research use.",
        "methodology": "Any method is allowed, including a neural network.",
        "deployment": "The lab uses the prediction before testing, with only pre-test measurements.",
        "difficulty": "The Smith model reports AUROC 0.81 on its published split; its code is available.",
    }
    calls = provider(monkeypatch, [scope([update(key, value) for key, value in facts.items()], "evaluation", "Should evaluation hold out entire material families?")])
    c.submit_message(project, " ".join(facts.values()), "brief")
    state = c.ensure_conversation(project)
    assert all(state["items"][key]["value"] == value for key, value in facts.items())
    assert state["current_question"]["field"] == "evaluation"
    view = c.conversation_view(project)
    assert view["interview"]["current_stage"] == "problem"
    assert view["interview"]["stages"][2]["status"] == "answered"
    assert state["items"]["trial"]["status"] == "missing"
    context = json.loads(calls[0]["input"])
    assert context["application_owned_items"] == ["trial"]
    assert "neural network is a method" in calls[0]["instructions"]
    assert "optional" in c._render(project).lower()
    assert "reported" in c._render(project).lower()


@pytest.mark.parametrize("suggested", ["organizer", "competition", "submissions", "trial"])
def test_model_cannot_interrupt_scientific_interview_with_admin_or_execution_proof(monkeypatch, project, suggested):
    provider(monkeypatch, [scope([update("question", "Predict stability.")], suggested, "Provide this detail?")])
    c.submit_message(project, "Predict stability.", "first")
    assert project["conversation"]["current_question"]["field"] == "task"


def test_no_human_followup_is_requested_for_application_baseline_work(project):
    state = c.ensure_conversation(project)
    for key, item in state["items"].items():
        if key != "trial":
            item.update(status="deferred", gap="Unknown for now.")
    c._advance(project, None, {"question_field": "trial", "question_text": "Can you run the evaluator?"})
    assert state["phase"] == "draft" and state["current_question"] is None
    assert state["items"]["trial"]["status"] == "missing"
    assert "reference baseline is optional" in state["readme"].lower()


def test_reported_baseline_run_does_not_become_verified_execution(monkeypatch, project):
    claim = "We ran the baseline and got 0.9."
    provider(monkeypatch, [scope([update("trial", claim)])])
    c.submit_message(project, claim, "reported")
    item = project["conversation"]["items"]["trial"]
    assert item["value"] == claim
    assert item["status"] == "partial"
    assert "Application execution evidence" in item["gap"]
    assert project["conversation"]["current_question"]["field"] != "trial"


def test_existing_draft_gains_interview_fields_without_losing_evidence_or_retry(project):
    state = c.ensure_conversation(project)
    state["items"]["difficulty"].update(status="answered", value="Published score 0.81.", gap="")
    for key in ("methodology", "deployment"):
        state["items"].pop(key)
    state.update(readme="# Existing draft", status="error", can_retry=True, _pending={"kind": "draft"})
    before = copy.deepcopy(state["messages"])
    migrated = c.ensure_conversation(project)
    assert migrated["items"]["difficulty"]["value"] == "Published score 0.81."
    assert migrated["messages"] == before
    assert migrated["status"] == "error" and migrated["can_retry"]
    assert migrated["_pending"] == {"kind": "draft"}
    assert "### Methodology" in migrated["readme"]
    assert "### Deployment and evaluation" in migrated["readme"]


@pytest.mark.parametrize("bad", [
    "invalid JSON", [], {"updates": []},
    scope([update("question", "not in the message")]),
    scope([update("question", "Predict stability", "invented")]),
    scope([update("question", "Predict stability", gap="Still missing something")]),
    scope([update("question", "Predict stability"), update("question", "Predict stability")]),
    scope([update("unknown-field", "Predict stability")]),
    scope([update("question", "Predict stability", operation="correct", supersedes=["old"])]),
    scope(field="task", question=""),
    SimpleNamespace(status="incomplete", output_text="{}"),
])
def test_bad_output_preserves_message_and_facts_and_exposes_retry(monkeypatch, project, bad):
    provider(monkeypatch, [bad])
    c.submit_message(project, "Predict stability", "first")
    state = c.ensure_conversation(project)
    assert state["status"] == "error" and state["can_retry"]
    assert len(users(state)) == 1
    assert all(item["status"] == "missing" for item in state["items"].values())
    assert project["_model_calls"] == 1


def test_error_retry_uses_saved_message_and_new_request_id(monkeypatch, project):
    calls = provider(monkeypatch, [RuntimeError("SECRET provider details"), scope([update("question", "Predict stability")])])
    c.submit_message(project, "Predict stability", "first")
    state = c.ensure_conversation(project)
    assert "SECRET" not in state["error"]
    c.submit_message(project, "Predict stability", "first")
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Retry"):
        c.submit_message(project, "A different answer", "second")
    c.retry_turn(project, "retry-1")
    snapshot = copy.deepcopy(state)
    c.retry_turn(project, "retry-1")
    assert state == snapshot
    assert len(calls) == 2 and len(users(state)) == 1
    assert state["items"]["question"]["value"] == "Predict stability"
    assert state["status"] == "idle" and not state["can_retry"]


def test_request_id_cannot_represent_two_actions(project):
    c.submit_message(project, "A research idea", "same")
    with pytest.raises(ValueError, match="different action"):
        c.make_readme(project, "same")
    with pytest.raises(ValueError, match="different action"):
        c.submit_message(project, "A changed research idea", "same")


def test_failure_then_draft_keeps_unprocessed_initial_brief(monkeypatch, project):
    calls = provider(monkeypatch, [RuntimeError("provider unavailable"), draft()])
    text = "Our private material dataset has 500 observations and compute budget USD 20."
    c.submit_message(project, text, "first")
    c.make_readme(project, "draft")
    state = c.ensure_conversation(project)
    assert len(calls) == 2
    assert "Messages awaiting manual review" in state["readme"]
    assert text in state["readme"]
    assert all(item["status"] == "missing" for item in state["items"].values())
    assert any(message["content"] == text for message in state["messages"])


def test_budget_is_reserved_before_call_and_no_automatic_twelfth_retry(monkeypatch, project):
    project["_model_calls"] = 11
    snapshots = []
    calls = provider(monkeypatch, [RuntimeError("timeout")], reserve_check=lambda: snapshots and snapshots[-1]["_model_calls"] == 12 or pytest.fail("Call not reserved"))
    c.submit_message(project, "Our research has a distinct goal", "first", reserve=lambda p: snapshots.append(copy.deepcopy(p)))
    assert snapshots[-1]["conversation"]["_inflight"]
    assert len(users(snapshots[-1]["conversation"])) == 1
    assert not c.ensure_conversation(project)["can_retry"]
    with pytest.raises(ValueError, match="12-call"):
        c.retry_turn(project, "retry")
    c.make_readme(project, "draft")
    state = c.ensure_conversation(project)
    assert len(calls) == 1 and project["_model_calls"] == 12
    assert state["readme"] and "Our research has a distinct goal" in state["readme"]
    assert not state["can_retry"]


def test_restart_recovery_does_not_make_call_or_duplicate_user_message(monkeypatch, project):
    snapshots = []
    calls = provider(monkeypatch, [scope([update("question", "Predict stability")]), scope([update("question", "Predict stability")])])
    c.submit_message(project, "Predict stability", "first", reserve=lambda p: snapshots.append(copy.deepcopy(p)))
    recovered = snapshots[0]
    assert c.recover_interrupted(recovered)
    assert not c.recover_interrupted(recovered)
    state = c.ensure_conversation(recovered)
    assert state["status"] == "error" and state["can_retry"]
    assert len(calls) == 1
    c.submit_message(recovered, "Predict stability", "first")
    assert len(calls) == 1
    c.retry_turn(recovered, "retry")
    assert len(calls) == 2 and len(users(state)) == 1
    assert recovered["_model_calls"] == 2


def test_specific_correction_keeps_other_plan_facts_and_revises_draft(monkeypatch, project):
    original = "Alice owns the work. Deadline is 1 December. Compute costs USD 20. Tokens cost USD 5."
    corrected = "Correction: compute costs USD 40."
    calls = provider(monkeypatch, [scope([update("plan", original)]), draft(), scope([update("plan", corrected, operation="correct", supersedes=["Compute costs USD 20."])]), draft("Revised plan")])
    c.submit_message(project, original, "first")
    c.make_readme(project, "draft")
    old_readme = c.ensure_conversation(project)["readme"]
    snapshots = []
    c.submit_message(project, corrected, "correction", reserve=lambda p: snapshots.append(copy.deepcopy(p)))
    state = c.ensure_conversation(project)
    value = state["items"]["plan"]["value"]
    assert "Alice owns the work" in value and "Deadline is 1 December" in value and "Tokens cost USD 5" in value
    assert "USD 20" not in value and "USD 40" in value
    assert state["readme"] != old_readme and "USD 40" in state["readme"]
    assert snapshots[0]["conversation"]["readme"] is None
    assert len(calls) == 4 and state["phase"] == "draft"
    assert any("USD 20" in event["before"]["value"] for event in state["_history"])


@pytest.mark.parametrize("supersedes", [["not in the old answer"], ["USD 20", "20"], ["USD 20", "USD 20"], []])
def test_bad_correction_spans_cannot_remove_previous_facts(monkeypatch, project, supersedes):
    original = "Alice owns the work. Compute costs USD 20."
    correction = "Correction: compute is USD 40."
    new = update("plan", [correction] * max(1, len(supersedes)), operation="correct", supersedes=supersedes)
    provider(monkeypatch, [scope([update("plan", original)]), scope([new])])
    c.submit_message(project, original, "first")
    c.submit_message(project, correction, "correct")
    state = c.ensure_conversation(project)
    assert state["status"] == "error"
    assert state["items"]["plan"]["value"] == original


def test_correction_preserves_repeated_replacement_evidence(monkeypatch, project):
    original = "Alice owns the work. Budget: $20 in compute. Cost summary: $20 compute. Tokens: $5."
    correction = "Correction: replace the compute budget everywhere with $50."
    proposal = update("plan", ["$50", "$50"], operation="correct", supersedes=["$20 in compute", "$20 compute"])
    provider(monkeypatch, [scope([update("plan", original)]), scope([proposal])])
    c.submit_message(project, original, "first")
    c.submit_message(project, correction, "correct")
    state = c.ensure_conversation(project)
    assert state["status"] == "idle"
    value = state["items"]["plan"]["value"]
    assert value.count("$50") == 2 and "$20" not in value
    assert "Alice owns the work" in value and "Tokens: $5" in value
    assert state["items"]["plan"]["evidence"][-1]["quotes"] == ["$50", "$50"]
    assert "Budget: $50 in compute" in value and "Cost summary: $50 compute" in value


def test_whole_correction_sentence_changes_amount_without_inserting_instructions(monkeypatch, project):
    first = "One credible attempt could cost about $20 in compute and $5 in model tokens."
    second = "The resource estimate is $20 compute plus $5 tokens per attempt."
    original = "Alice owns the work. Deadline is 1 December. " + first + " " + second
    correction = "Correction: change the compute budget per attempt from $20 to $50 everywhere it appears."
    proposal = update("plan", [correction, correction], operation="correct", supersedes=["$20 in compute", "$20 compute"])
    provider(monkeypatch, [scope([update("plan", original)]), scope([proposal])])
    c.submit_message(project, original, "first")
    c.submit_message(project, correction, "correct")
    state = c.ensure_conversation(project)
    assert state["status"] == "idle"
    expected = original.replace("$20", "$50")
    assert state["items"]["plan"]["value"] == expected
    assert "Correction:" not in state["items"]["plan"]["value"]
    assert state["items"]["plan"]["evidence"][-1]["quotes"] == [correction, correction]
    event = state["_history"][-1]
    assert event["replacement_evidence"] == [correction, correction]
    assert event["supersedes"] == ["$20 in compute", "$20 compute"]
    assert event["before"]["value"] == original


@pytest.mark.parametrize("old,evidence,expected", [
    ("$20 in compute", "Correction: change from $20 to $50 everywhere.", "$50 in compute"),
    ("USD 20 in compute", "Change from USD 20 to USD 50.", "USD 50 in compute"),
    ("$1,200.50 in compute", "Update from $1,200.50 to $1,500.75.", "$1,500.75 in compute"),
    ("$20 compute", "$50", "$50 compute"),
    ("compute $20 and tokens $5", "Change from $20 to $50.", "compute $50 and tokens $5"),
    # Do not substitute a prefix of a different amount or guess ambiguous spans.
    ("$200 in compute", "Change from $20 to $50.", "Change from $20 to $50."),
    ("$20.25 in compute", "Change from $20 to $50.", "Change from $20 to $50."),
    ("$20 compute and $20 more", "Change from $20 to $50.", "Change from $20 to $50."),
])
def test_amount_replacement_is_narrow_and_preserves_context(old, evidence, expected):
    assert c._replacement_text(old, evidence) == expected


def test_draft_metadata_does_not_replace_authoritative_answers(monkeypatch, project):
    provider(monkeypatch, [scope([update("question", "Predict stability")]), {**draft(), "intro": "A proposed framing, not a factual replacement."}])
    c.submit_message(project, "Predict stability", "first")
    c.make_readme(project, "draft")
    state = c.ensure_conversation(project)
    assert state["items"]["question"]["value"] == "Predict stability"
    assert "Suggested framing" in state["readme"] and "authoritative" in state["readme"]
    assert "Pending organizer review" in state["readme"]
    assert "Status: Missing" in state["readme"]


def test_draft_failure_has_deterministic_body_and_retries_only_draft(monkeypatch, project):
    calls = provider(monkeypatch, [scope([update("question", "Predict stability")]), RuntimeError("draft timeout"), draft()])
    c.submit_message(project, "Predict stability", "first")
    c.make_readme(project, "draft")
    state = c.ensure_conversation(project)
    assert state["status"] == "error" and state["readme"]
    assert "Predict stability" in state["readme"]
    c.retry_turn(project, "retry")
    assert state["status"] == "idle"
    assert [call["reasoning"]["effort"] for call in calls] == ["medium", "high", "high"]
    assert len(users(state)) == 2


def test_deliberate_title_is_preserved(monkeypatch, project):
    project["title"] = "Scientist's chosen title"
    provider(monkeypatch, [draft("Model suggestion")])
    c.make_readme(project, "draft")
    assert project["title"] == "Scientist's chosen title"
    assert c.ensure_conversation(project)["readme"].startswith("# Scientist&#x27;s chosen title")


def test_rules_revision_can_name_an_explicit_checklist_item(project):
    c.make_readme(project, "draft")
    c.submit_message(project, "Plan: Alice owns the work and compute costs USD 40.", "revision")
    state = c.ensure_conversation(project)
    assert state["items"]["plan"]["status"] == "partial"
    assert "Alice" in state["items"]["plan"]["value"]
    assert state["phase"] == "draft"
    assert "Alice" in state["readme"]


def test_unknown_after_draft_needs_an_item_and_does_not_clear_answers(project):
    c.submit_message(project, "A research idea", "start")
    c.make_readme(project, "draft")
    state = c.ensure_conversation(project)
    previous = copy.deepcopy(state["items"])
    c.submit_message(project, "I don't know", "unknown")
    assert state["items"] == previous
    assert state["readme"] and state["current_question"] is None
    c.submit_message(project, "Task: unknown", "named-unknown")
    assert state["items"]["task"]["status"] == "deferred"
    assert "Deferred" in state["readme"]


def recorded_bridge_project():
    project = {"answers": {"objective": "", "prediction_unit": "", "success_criterion": "",
                            "data_origin": "unknown", "labels_public": "unknown", "rights": "unknown",
                            "compute_budget": "USD 20–40, as recorded", "token_budget": "Unknown"},
               "conversation": {"items": {
                   "question": {"status": "answered", "value": "Predict material stability.\nThis would reduce failed experiments.", "evidence": [{"quotes": ["Predict material stability."]}]},
                   "task": {"status": "answered", "value": "One prediction per material sample.\nPredict stable or unstable; balanced accuracy above 0.75 is useful.", "evidence": [{"quotes": ["One prediction per material sample."]}]},
                   "data": {"status": "answered", "value": "Private data; labels are not public; we have permission."},
                   "plan": {"status": "answered", "value": "USD 50 compute and USD 8 model tokens."},
               }}}
    return project


def test_bridge_migrates_complete_recorded_chat_without_new_questions():
    from autokaggle.policy import brief_checks

    project = recorded_bridge_project()
    original_chat = copy.deepcopy(project["conversation"])
    assert c.sync_legacy_answers(project)
    answers = project["answers"]
    assert answers["objective"] == original_chat["items"]["question"]["value"]
    assert answers["prediction_unit"] == answers["success_criterion"] == original_chat["items"]["task"]["value"]
    assert project["conversation"] == original_chat
    assert all(check["severity"] == "pass" for check in brief_checks(project) if check["id"] in {"objective", "prediction_unit", "success_criterion"})
    assert project["_chat_derived_answers"]["objective"] == {"source_item": "question", "value": answers["objective"]}
    snapshot = copy.deepcopy(project)
    assert not c.sync_legacy_answers(project)
    assert project == snapshot


def test_bridge_preserves_supported_task_facts_when_metric_is_manually_bypassed():
    project = recorded_bridge_project()
    task = project["conversation"]["items"]["task"]
    task["requirements"] = {identifier: recorded_requirement(task["value"]) for identifier in ("inputs", "outputs", "metric")}
    c.sync_legacy_answers(project)
    expected = {key: project["answers"][key] for key in ("prediction_unit", "success_criterion")}
    task["bypasses"] = {"metric": {"reason": "The organizer wants the score choice treated as provisional."}}
    assert not c.sync_legacy_answers(project)
    assert {key: project["answers"][key] for key in expected} == expected


def test_bridge_bypass_does_not_supply_missing_metric_or_erase_valid_unit():
    project = recorded_bridge_project()
    task = project["conversation"]["items"]["task"]
    task["requirements"] = {identifier: recorded_requirement(task["value"]) for identifier in ("inputs", "outputs", "metric")}
    c.sync_legacy_answers(project)
    unit = project["answers"]["prediction_unit"]
    task["requirements"]["metric"] = {"status": "missing", "reason": "The previous metric needs revision."}
    task["bypasses"] = {"metric": {"reason": "The organizer accepts an exploratory scoring pilot."}}
    assert c.sync_legacy_answers(project)
    assert project["answers"]["prediction_unit"] == unit
    assert project["answers"]["success_criterion"] == ""


def test_bridge_bypassed_missing_inputs_do_not_erase_a_recorded_metric():
    project = recorded_bridge_project()
    task = project["conversation"]["items"]["task"]
    task["requirements"] = {"metric": recorded_requirement(task["value"]), "outputs": recorded_requirement(task["value"])}
    task["bypasses"] = {"inputs": {"reason": "Inputs will be supplied in a later revision."}}
    c.sync_legacy_answers(project)
    assert project["answers"]["prediction_unit"] == ""
    assert project["answers"]["success_criterion"] == task["value"]


@pytest.mark.parametrize("status", ["missing", "partial", "deferred"])
def test_bridge_does_not_fill_audit_answers_from_incomplete_items(status):
    project = recorded_bridge_project()
    for key in ("question", "task"):
        project["conversation"]["items"][key]["status"] = status
    before = copy.deepcopy(project)
    assert not c.sync_legacy_answers(project)
    assert project == before


@pytest.mark.parametrize("value", ["unknown", "not sure", "TBD", "I don't know", ""])
def test_bridge_does_not_promote_unknown_text_even_if_item_is_marked_answered(value):
    project = recorded_bridge_project()
    for key in ("question", "task"):
        project["conversation"]["items"][key]["value"] = value
    assert not c.sync_legacy_answers(project)
    assert all(project["answers"][key] == "" for key in ("objective", "prediction_unit", "success_criterion"))


def test_bridge_preserves_existing_manual_answers_and_data_declarations():
    project = recorded_bridge_project()
    project["answers"].update(objective="An explicit manual objective", prediction_unit="Unknown", success_criterion="Manual threshold")
    before = copy.deepcopy(project)
    assert not c.sync_legacy_answers(project)
    assert project == before


def test_bridge_does_not_infer_permissions_or_parse_budget_text():
    project = recorded_bridge_project()
    retained = {key: project["answers"][key] for key in ("data_origin", "labels_public", "rights", "compute_budget", "token_budget")}
    c.sync_legacy_answers(project)
    assert {key: project["answers"][key] for key in retained} == retained
    assert project["conversation"]["items"]["plan"]["value"] == "USD 50 compute and USD 8 model tokens."


def test_bridge_updates_chat_corrections_only_while_values_are_auto_derived():
    project = recorded_bridge_project()
    c.sync_legacy_answers(project)
    project["answers"]["prediction_unit"] = "A manual patient-level unit"
    project["conversation"]["items"]["question"]["value"] = "A corrected scientific objective"
    project["conversation"]["items"]["task"]["value"] = "A corrected task and success measure"
    assert c.sync_legacy_answers(project)
    assert project["answers"]["objective"] == "A corrected scientific objective"
    assert project["answers"]["success_criterion"] == "A corrected task and success measure"
    assert project["answers"]["prediction_unit"] == "A manual patient-level unit"
    assert "prediction_unit" in project["_chat_manual_answers"]
    assert "prediction_unit" not in project["_chat_derived_answers"]


@pytest.mark.parametrize("manual_value", ["", "same"])
def test_explicit_manual_blank_or_same_value_edit_stops_future_auto_updates(manual_value):
    project = recorded_bridge_project()
    c.sync_legacy_answers(project)
    original = project["answers"]["objective"]
    project["answers"]["objective"] = "" if manual_value == "" else original
    assert not c.sync_legacy_answers(project, manual_fields=["objective"])
    project["conversation"]["items"]["question"]["value"] = "New chat objective"
    assert not c.sync_legacy_answers(project)
    assert project["answers"]["objective"] == ("" if manual_value == "" else original)


def test_manual_blank_before_first_bridge_is_preserved():
    project = recorded_bridge_project()
    assert c.sync_legacy_answers(project, manual_fields=["objective", "rights"])
    assert project["answers"]["objective"] == ""
    assert project["_chat_manual_answers"] == ["objective"]
    assert not c.sync_legacy_answers(project)
    assert project["answers"]["objective"] == ""


def test_bridge_clears_only_auto_answers_when_chat_item_is_withdrawn():
    project = recorded_bridge_project()
    c.sync_legacy_answers(project)
    project["answers"]["prediction_unit"] = "Manual unit remains"
    c.sync_legacy_answers(project, manual_fields=["prediction_unit"])
    project["conversation"]["items"]["task"]["status"] = "deferred"
    assert c.sync_legacy_answers(project)
    assert project["answers"]["prediction_unit"] == "Manual unit remains"
    assert project["answers"]["success_criterion"] == ""
    project["conversation"]["items"]["task"].update(status="answered", value="A newly confirmed task")
    assert c.sync_legacy_answers(project)
    assert project["answers"]["success_criterion"] == "A newly confirmed task"
    assert project["answers"]["prediction_unit"] == "Manual unit remains"


def test_bridge_noops_for_legacy_only_project_and_does_not_run_during_reads():
    legacy = {"answers": {"objective": "Existing legacy objective"}}
    snapshot = copy.deepcopy(legacy)
    assert not c.sync_legacy_answers(legacy)
    assert legacy == snapshot
    project = {"title": "New challenge", "answers": {}, "_model_calls": 0}
    state = c.ensure_conversation(project)
    state["items"]["question"].update(status="answered", value="Recorded objective")
    c.conversation_view(project)
    assert project["answers"] == {}


def revision_project(project):
    state = c.ensure_conversation(project)
    state['items']['question'].update(status='answered', value='Predict battery life.', gap='')
    state['items']['deployment'].update(status='answered', value='Run once per battery cycle.', gap='')
    state['items']['evaluation'].update(status='partial', value='Use a random split.', gap='Which batteries belong together?')
    state['_asked'] = ['evaluation', 'deployment', 'difficulty']
    state['followups'] = 8
    c.make_readme(project, 'initial-draft')
    return state


def test_revision_data_question_requests_link_and_stops_duplicate_followups(monkeypatch, project):
    state = revision_project(project)
    c.begin_revision(project, "start")
    question = "Which simulation source should replace the existing dataset?"
    provider(monkeypatch, [scope([], "data", question), scope([], "data", question), scope([], "data", question)])
    c.submit_message(project, "Replace the dataset with new planetary simulations.", "change")
    assert "Google Drive" in state["current_question"]["text"]
    c.submit_message(project, "I need to check with the research team.", "clarify")
    assert state["current_question"]["requirement_id"] == "source"
    c.submit_message(project, "The research team still has to identify it.", "clarify-again")
    assert state["current_question"] is None
    assert c.conversation_view(project)["review"]["followups"] == 2
    assert state["scope_checkpoint"]["requirement_id"] == "source"


def test_begin_revision_preserves_draft_context_and_is_idempotent(project):
    state = revision_project(project)
    project['workflow'] = {'version': 'old-version', 'status': 'needs_changes',
                           'first_result': {'metric': 'mae', 'score': 2.5, 'rows': 10},
                           'checks': [{'id': 'baseline', 'status': 'blocked', 'detail': 'Source code is missing.'}]}
    previous = copy.deepcopy(state)
    c.begin_revision(project, 'review-start')
    view = c.conversation_view(project)
    assert view['review']['mode'] == 'revision'
    assert view['review']['status'] == 'awaiting_request'
    assert view['review']['round'] == 1 and not view['review']['can_start']
    assert view['review']['previous_version'] == 'old-version'
    assert state['readme'] == previous['readme']
    assert state['items'] == previous['items']
    assert state['messages'][:-1] == previous['messages']
    assert state['messages'][-1]['content'] == c.REVISION_MESSAGE
    saved = copy.deepcopy(state)
    c.begin_revision(project, 'review-start')
    assert state == saved
    c.begin_revision(project, 'review-start-again')
    assert len(state['_revision_rounds']) == 1
    assert state['messages'] == saved['messages']
    with pytest.raises(ValueError, match='different action'):
        c.submit_message(project, 'Different action', 'review-start')
    assert len(state['_revision_rounds']) == 1
    assert state['_revision_rounds'][0]['previous']['readme'] == previous['readme']


def test_begin_revision_requires_saved_idle_draft_without_consuming_id(project):
    state = c.ensure_conversation(project)
    with pytest.raises(ValueError, match='Create a draft'):
        c.begin_revision(project, 'start')
    assert 'start' not in state['_requests']
    c.make_readme(project, 'draft')
    state['status'] = 'error'
    with pytest.raises(ValueError, match='Finish or retry'):
        c.begin_revision(project, 'start')
    assert 'start' not in state['_requests']


def test_revision_clarifies_requested_change_and_can_revisit_a_field(monkeypatch, project):
    state = revision_project(project)
    old_readme = state['readme']
    c.begin_revision(project, 'start')
    calls = provider(monkeypatch, [
        scope([update('evaluation', 'Change evaluation to represent deployment.', 'partial', 'Which deployment conditions?')],
              'evaluation', 'Should evaluation hold out whole battery models?'),
        scope([update('evaluation', 'Yes, whole battery models.', 'partial', 'Which model groups?')],
              'evaluation', 'Which battery model groups should form the held-out set?'),
        scope([update('evaluation', 'Use the newest model group.', 'answered')]), draft('Revised battery challenge'),
    ])
    c.submit_message(project, 'Change evaluation to represent deployment.', 'change')
    assert state['phase'] == 'revision' and state['readme'] is None
    assert state['current_question']['field'] == 'evaluation'
    c.submit_message(project, 'Yes, whole battery models.', 'clarify')
    assert state['phase'] == 'revision'
    assert state['current_question']['field'] == 'evaluation'
    c.submit_message(project, 'Use the newest model group.', 'clarify-final')
    view = c.conversation_view(project)
    assert view['review']['status'] == 'draft_ready' and view['review']['can_start']
    assert view['review']['followups'] == 2
    assert view['review']['changed_fields'] == ['evaluation']
    assert len(view['review']['requested_changes']) == 1
    assert len(view['review']['clarified_changes']) == 2
    assert state['_revision_rounds'][0]['previous']['readme'] == old_readme
    assert state['items']['deployment']['value'] == 'Run once per battery cycle.'
    assert state['phase'] == 'draft' and len(calls) == 4
    assert 'data' not in [message.get('field') for message in [state.get('current_question') or {}]]


def test_revision_preserves_all_context_but_sends_no_private_metadata(monkeypatch, project):
    state = revision_project(project)
    from autokaggle import onboarding_setup
    onboarding_setup.update(project, {'organizer_email': 'owner@example.org'}, source='chat')
    c.make_readme(project, 'contact-draft')
    state['messages'].insert(1, {'id': 'early', 'role': 'user', 'content': 'An early context fact. Contact owner@example.org.'})
    project['workflow'] = {'version': 'v1', 'status': 'needs_changes',
        'first_result': {'metric': 'mae', 'score': 2.5, 'rows': 10, 'final_score': 'PRIVATE_FINAL_MARKER'},
        'checks': [{'id': 'baseline', 'status': 'blocked', 'label': 'Reference trial', 'detail': 'Reference source code is missing.'}],
        'submission_token': 'PRIVATE_TOKEN_MARKER', 'test_answers': 'PRIVATE_ANSWERS_MARKER',
        'artifacts': [{'name': 'baseline.py', 'content': 'PRIVATE_CONTENT_MARKER'}]}
    c.begin_revision(project, 'start')
    calls = provider(monkeypatch, [scope([], 'difficulty', 'Which source repository should the reference use?')])
    c.submit_message(project, 'Change our reference baseline.', 'feedback')
    text = calls[0]['input']
    context = json.loads(text)['revision_context']
    assert 'An early context fact' in text
    assert 'owner@example.org' not in text
    assert '[private organizer email]' in text
    assert context['previous_workflow']['first_result'] == {'metric': 'mae', 'score': 2.5, 'rows': 10}
    assert 'Reference source code is missing' in text
    assert 'baseline.py' in text
    for marker in ('PRIVATE_FINAL_MARKER', 'PRIVATE_TOKEN_MARKER', 'PRIVATE_ANSWERS_MARKER', 'PRIVATE_CONTENT_MARKER', 'private dataset marker', 'private-seed'):
        assert marker not in text
    assert 'organizer\'s revision assistant' in calls[0]['instructions']


def test_revision_has_new_budget_but_preserves_total_accounting(monkeypatch, project):
    state = revision_project(project)
    project['_model_calls'] = 12
    c.begin_revision(project, 'start')
    snapshots = []
    calls = provider(monkeypatch, [scope([], 'difficulty', 'Which baseline source should we use?')])
    c.submit_message(project, 'The baseline reference needs to change.', 'change', reserve=lambda value: snapshots.append(copy.deepcopy(value)))
    assert len(calls) == 1 and project['_model_calls'] == 13
    assert snapshots[0]['_model_calls'] == 13
    assert snapshots[0]['conversation']['_revision_rounds'][0]['model_calls'] == 1
    assert state['status'] == 'idle'
    assert c.conversation_view(project)['review']['model_calls'] == 1


def test_revision_retry_uses_round_budget_and_preserves_one_request(monkeypatch, project):
    state = revision_project(project)
    project['_model_calls'] = 12
    c.begin_revision(project, 'start')
    calls = provider(monkeypatch, [RuntimeError('provider timeout'), scope([], 'difficulty', 'Which source should we use?')])
    c.submit_message(project, 'Change the reference.', 'change')
    assert state['can_retry']
    c.retry_turn(project, 'retry')
    assert state['status'] == 'idle' and len(calls) == 2
    assert len(c.conversation_view(project)['review']['requested_changes']) == 1
    assert project['_model_calls'] == 14


def test_revision_budget_exhaustion_keeps_unprocessed_feedback(project, monkeypatch):
    state = revision_project(project)
    c.begin_revision(project, 'start')
    state['_revision_rounds'][0]['model_calls'] = 12
    project['_model_calls'] = 24
    calls = provider(monkeypatch, [])
    c.submit_message(project, 'Change the baseline to the new reference.', 'change')
    assert not calls and state['phase'] == 'draft'
    assert 'Change the baseline to the new reference.' in state['readme']
    assert state['_revision_rounds'][0]['status'] == 'draft_ready'


def test_revision_repeated_question_drafts_instead_of_looping(monkeypatch, project):
    state = revision_project(project)
    c.begin_revision(project, 'start')
    calls = provider(monkeypatch, [scope([], 'difficulty', 'Which source should we use?'),
                                   scope([], 'difficulty', 'Which source should we use?'), draft()])
    c.submit_message(project, 'Change the baseline.', 'change')
    c.submit_message(project, 'I need help choosing a source.', 'answer')
    assert state['phase'] == 'draft' and len(calls) == 3
    assert state['_revision_rounds'][0]['followups'] == 1


def test_revision_stops_after_eight_clarifications(monkeypatch, project):
    state = revision_project(project)
    c.begin_revision(project, 'start')
    targets = [('question', 'scope'), ('question', 'value'), ('task', 'inputs'), ('task', 'outputs'),
               ('data', 'source'), ('data', 'permission'), ('methodology', 'methods'), ('deployment', 'setting'), ('evaluation', 'population')]
    responses = [{**scope([], field, f'Which condition {number} should apply?', requirements=[]), 'question_requirement_id': identifier,
                  'question_why': 'This decision defines the proposed revision.'} for number, (field, identifier) in enumerate(targets)] + [draft()]
    calls = provider(monkeypatch, responses)
    c.submit_message(project, 'Change the reference method.', 'change')
    for number in range(8):
        c.submit_message(project, f'Additional requested detail {number}.', f'detail-{number}')
    assert state['phase'] == 'draft' and len(calls) == 10
    assert state['_revision_rounds'][0]['followups'] == 8
    assert state['followups'] == 8  # The initial interview count is preserved.


def test_revision_cannot_ask_for_application_execution(monkeypatch, project):
    state = revision_project(project)
    c.begin_revision(project, 'start')
    provider(monkeypatch, [scope([update('trial', 'The baseline reproduced perfectly.')], 'trial', 'Can you prove execution?'), draft()])
    c.submit_message(project, 'The baseline reproduced perfectly.', 'feedback')
    assert state['phase'] == 'draft'
    assert state['items']['trial']['status'] == 'partial'
    assert 'execution evidence' in state['items']['trial']['gap']
    assert state['_revision_rounds'][0]['followups'] == 0


def test_new_feedback_after_revision_draft_starts_new_round_and_keeps_version(monkeypatch, project):
    state = revision_project(project)
    c.begin_revision(project, 'start')
    c.make_readme(project, 'revised-draft')
    old = state['readme']
    calls = provider(monkeypatch, [scope([], 'deployment', 'When should the method run?')])
    c.submit_message(project, 'Change the deployment timing.', 'new-change')
    assert len(state['_revision_rounds']) == 2
    assert state['_revision_rounds'][1]['previous']['readme'] == old
    assert len(calls) == 1
    saved = copy.deepcopy(state)
    c.submit_message(project, 'Change the deployment timing.', 'new-change')
    assert state == saved and len(calls) == 1


def test_model_extracts_specific_requirements_and_reuses_prior_researcher_evidence(monkeypatch, project):
    first = "Predict stability for compact three-planet systems. Inputs are masses in Earth masses and orbital elements at day 100."
    second = "Return one stability probability per system. Score the mean log loss; lower is better."
    calls = provider(monkeypatch, [
        scope([update("question", "Predict stability for compact three-planet systems."),
               update("task", "Inputs are masses in Earth masses and orbital elements at day 100.")],
              "task", "What should each submitted result contain?", requirements=[
                  requirement("question", "scope", "Predict stability for compact three-planet systems."),
                  requirement("task", "inputs", "Inputs are masses in Earth masses and orbital elements at day 100.")]),
        scope([update("task", second)], "question", "What improvement would count as useful scientific progress?", requirements=[
            requirement("task", "inputs", "Inputs are masses in Earth masses and orbital elements at day 100."),
            requirement("task", "outputs", "Return one stability probability per system."),
            requirement("task", "metric", "Score the mean log loss; lower is better.")]),
    ])
    c.submit_message(project, first, "specific-brief")
    c.submit_message(project, second, "specific-output")
    state = c.ensure_conversation(project)
    view = c.conversation_view(project)
    task = next(item for item in view["checklist"] if item["id"] == "task")
    assert task["understanding"]["completed"] == task["understanding"]["total"] == 3
    assert task["understanding"]["score"] == 100
    assert state["items"]["task"]["requirements"]["inputs"]["evidence"] == ["Inputs are masses in Earth masses and orbital elements at day 100."]
    assert state["items"]["question"]["requirements"]["scope"]["status"] == "recorded"
    assert view["readiness"]["completed"] == 4 and not view["readiness"]["ready"]
    schema = calls[0]["text"]["format"]["schema"]
    assert "requirements" in schema["required"]
    assert len(calls) == 2


@pytest.mark.parametrize("bad", [
    requirement("question", "invented", "Predict stability."),
    requirement("unknown_field", "scope", "Predict stability."),
    requirement("organizer", "contact", "Predict stability."),
    requirement("trial", "execution", "Predict stability."),
    requirement("question", "scope", "I invented this statement."),
    requirement("question", "scope", [], "recorded"),
    requirement("question", "scope", "Predict stability.", "not_applicable", "It is not useful."),
    requirement("data", "outcomes", "Predict stability.", "not_applicable", ""),
    requirement("data", "outcomes", "unknown", "not_applicable", "Optimization does not use target labels."),
    requirement("question", "scope", [], "missing", ""),
    requirement("question", "scope", "unknown", "recorded"),
])
def test_invalid_requirement_response_is_atomic_and_retryable(monkeypatch, project, bad):
    state = c.ensure_conversation(project)
    before = copy.deepcopy(state["items"])
    provider(monkeypatch, [scope([update("question", "Predict stability.")], requirements=[bad])])
    c.submit_message(project, "Predict stability. The labels are unknown.", "invalid-requirement")
    assert state["status"] == "error" and state["can_retry"]
    assert state["items"] == before
    assert len(users(state)) == 1
    assert not state.get("_requirements_assessed")


def test_duplicate_requirement_response_is_rejected_without_partial_completion(monkeypatch, project):
    value = requirement("question", "scope", "Predict stability.")
    provider(monkeypatch, [scope([update("question", "Predict stability.")], requirements=[value, value])])
    c.submit_message(project, "Predict stability.", "duplicate-requirement")
    state = c.ensure_conversation(project)
    assert state["status"] == "error"
    assert state["items"]["question"]["value"] == ""
    assert c.conversation_view(project)["readiness"]["completed"] == 0


def test_requirement_cannot_cite_a_fact_removed_by_the_same_correction(monkeypatch, project):
    original = "We have 100 batteries with lifetime labels."
    correction = "Correction: labels are not available yet."
    provider(monkeypatch, [
        scope([update("data", original)], requirements=[requirement("data", "outcomes", "with lifetime labels.")]),
        scope([update("data", "labels are not available yet.", "partial", "Which labels will exist?", "correct", ["with lifetime labels."])],
              requirements=[requirement("data", "outcomes", "with lifetime labels.")]),
    ])
    c.submit_message(project, original, "labeled")
    saved = copy.deepcopy(project["conversation"]["items"])
    c.submit_message(project, correction, "not-labeled")
    assert project["conversation"]["status"] == "error"
    assert project["conversation"]["items"] == saved


def test_correction_rechecks_cross_field_evidence_and_keeps_unrelated_facts(monkeypatch, project):
    original = "Stability means no collision or ejection for 5 Gyr. Inputs are initial masses and orbital elements."
    source = "Stability means no collision or ejection for 5 Gyr."
    provider(monkeypatch, [
        scope([update("data", source), update("task", "Inputs are initial masses and orbital elements.")], requirements=[
            requirement("data", "outcomes", source), requirement("task", "outputs", source),
            requirement("task", "inputs", "Inputs are initial masses and orbital elements.")]),
        scope([update("data", "Stability now means no collision or ejection for 1 Gyr.", operation="correct", supersedes=[source])], requirements=[]),
    ])
    c.submit_message(project, original, "long-horizon")
    c.submit_message(project, "Correction: Stability now means no collision or ejection for 1 Gyr.", "short-horizon")
    items = project["conversation"]["items"]
    assert items["data"]["requirements"]["outcomes"]["status"] == "missing"
    assert items["task"]["requirements"]["outputs"]["status"] == "missing"
    assert items["task"]["requirements"]["inputs"]["status"] == "recorded"
    assert "initial masses and orbital elements" in items["task"]["value"]


def test_append_preserves_previously_supported_criteria(monkeypatch, project):
    first = "Predict long-term planetary stability."
    provider(monkeypatch, [
        scope([update("question", first)], requirements=[requirement("question", "scope", first)]),
        scope([update("question", "Focus only on systems with three planets.")], requirements=[]),
    ])
    c.submit_message(project, first, "broad-scope")
    c.submit_message(project, "Focus only on systems with three planets.", "narrow-scope")
    item = project["conversation"]["items"]["question"]
    assert first in item["value"] and "three planets" in item["value"]
    assert item["requirements"]["scope"]["status"] == "recorded"
    assert c._item_understanding("question", item)["score"] == 33


def test_initial_interview_can_ask_two_distinct_questions_for_one_field(monkeypatch, project):
    calls = provider(monkeypatch, [
        scope([], "question", "Which planetary systems should this cover?", requirements=[]),
        scope([], "question", "Which scientific improvement would make the prediction useful?", requirements=[]),
        scope([], "question", "Which other scientific improvement would count?", requirements=[]),
    ])
    c.submit_message(project, "I want to study stability.", "vague-start")
    assert project["conversation"]["current_question"]["field"] == "question"
    c.submit_message(project, "There are several kinds of planetary systems.", "scope-detail")
    assert project["conversation"]["current_question"]["field"] == "question"
    c.submit_message(project, "It should help us understand observed systems.", "value-detail")
    state = project["conversation"]
    assert state["_asked"].count("question") == 2
    assert state["current_question"] is None
    assert state["scope_checkpoint"]["field"] == "question"
    assert len(calls) == 3
    assert not c.conversation_view(project)["readiness"]["ready"]


def test_compulsory_unknown_remains_blocking_without_repeated_question(monkeypatch, project):
    provider(monkeypatch, [scope([], "data", "Which dataset provides the stability labels?", requirements=[])])
    c.submit_message(project, "Study planetary stability.", "brief")
    c.submit_message(project, "I don't know", "unknown-data")
    view = c.conversation_view(project)
    assert view["current_question"]["field"] != "data"
    assert {b["requirement_id"] for b in view["readiness"]["blockers"] if b["field"] == "data"} == {"source", "outcomes", "permission"}
    assert next(item for item in view["checklist"] if item["id"] == "data")["understanding"]["completed"] == 0


def test_invalid_recorded_requirement_is_open_in_public_view(project):
    state = c.ensure_conversation(project)
    state["items"]["question"]["requirements"] = {"scope": {"status": "recorded", "value": "Predict stability.", "evidence": [], "reason": ""}}
    item = next(item for item in c.conversation_view(project)["checklist"] if item["id"] == "question")
    assert item["requirements"][0]["status"] == "missing"
    assert "supporting evidence" in item["requirements"][0]["reason"]
    assert item["understanding"]["completed"] == 0


def test_continue_interview_is_idempotent_and_resets_round_budget(monkeypatch, project):
    c.submit_message(project, "Study planetary stability.", "first")
    c.make_readme(project, "checkpoint")
    project["_model_calls"] = 12
    before = copy.deepcopy(project["conversation"]["messages"])
    snapshots = []
    c.continue_interview(project, "continue-round", reserve=lambda value: snapshots.append(copy.deepcopy(value)))
    state = project["conversation"]
    assert state["messages"][:len(before)] == before
    assert state["_interview_round"] == 2
    assert state["_interview_call_start"] == 12
    assert state["followups"] == 1
    assert c._call_count(project) == 0
    saved = copy.deepcopy(state)
    c.continue_interview(project, "continue-round")
    assert state == saved
    assert snapshots[-1]["conversation"] == state
    provider(monkeypatch, [scope([], "task", "What output should an attempt produce?", requirements=[])])
    c.submit_message(project, "We mean compact systems of three planets.", "continued-answer")
    assert project["_model_calls"] == 13 and c._call_count(project) == 1
    with pytest.raises(ValueError, match="different action"):
        c.make_readme(project, "continue-round")


def test_continue_interview_keeps_unknowns_open_without_asking_again(project):
    c.submit_message(project, "Study planetary stability.", "first")
    skipped = project["conversation"]["current_question"]["field"]
    c.skip_question(project, "unknown-field")
    c.make_readme(project, "checkpoint")
    c.continue_interview(project, "continue")
    state = project["conversation"]
    assert state["current_question"]["field"] != skipped
    assert state["items"][skipped]["status"] == "deferred"
    assert any(blocker["field"] == skipped for blocker in c.conversation_view(project)["readiness"]["blockers"])


@pytest.mark.parametrize("guard", ["no_draft", "working", "pending", "inflight", "round_limit", "revision", "active_phase", "active_question"])
def test_continue_rejects_invalid_state_without_consuming_request(project, guard):
    state = c.ensure_conversation(project)
    if guard != "no_draft":
        c.make_readme(project, "checkpoint")
    if guard == "working":
        state["status"] = "working"
    elif guard == "pending":
        state["_pending"] = {"kind": "scope"}
    elif guard == "inflight":
        state["_inflight"] = True
    elif guard == "round_limit":
        state["_interview_round"] = c.MAX_REVISION_ROUNDS
    elif guard == "revision":
        c.begin_revision(project, "revision-start")
    elif guard == "active_phase":
        state["phase"] = "conversation"
    elif guard == "active_question":
        state["current_question"] = {"field": "task", "text": "What should a solution produce?"}
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        c.continue_interview(project, "cannot-continue")
    assert state == before
    assert not c.conversation_view(project)["interview"]["can_continue"]


def test_complete_scientific_brief_can_be_defined_without_reference_baseline(monkeypatch, project):
    # A complete, novel prediction task must not require an existing method.
    facts = {
        "question": {"scope": "Predict 5 Gyr dynamical stability in compact three-planet systems.",
                     "value": "This reduces the simulation time needed to screen proposed observed systems.",
                     "success": "Useful progress is mean log loss below 0.20 with at most 100 days of input integration."},
        "task": {"inputs": "Each system supplies three masses in Earth masses and six orbital elements per planet at day 100.",
                 "outputs": "Return a single probability of stability in [0, 1] for every system ID.",
                 "metric": "Use unweighted mean binary log loss across systems; lower is better."},
        "data": {"source": "The simulation table is at https://example.org/simulated-planets.csv.",
                 "outcomes": "A stable label means no collision or ejection during a 5 Gyr integration; all other labels are unstable.",
                 "permission": "We own the simulations and permit research use and distribution of participant inputs under CC BY 4.0."},
        "methodology": {"methods": "Any method is allowed.", "resources": "External training data and pretrained models are prohibited."},
        "deployment": {"setting": "Use this as an offline scientific screening benchmark.",
                       "information": "The predictor sees only the first 100 simulated days and no later orbital states.",
                       "timing": "Run once for each system; no online updates or persistent state are allowed.",
                       "limits": "The platform may set runtime and memory limits; CPU only and no network access.",
                       "outcome": "The submitted probability is scored against the long-integration label; it estimates screening reliability rather than proving physical stability."},
        "evaluation": {"population": "Evaluation represents compact systems with three planets of 1 to 10 Earth masses.",
                       "independence": "The independent unit is a progenitor system; all perturbed versions of a progenitor stay in the same split.",
                       "holdout": "Use 70% training and 30% held-out systems; divide held-out systems equally into public and private scoring groups.",
                       "uncertainty": "Use 10,000 independent held-out progenitors and report a 95% bootstrap interval over progenitors.",
                       "workflow": "Score one fixed 5 Gyr stability outcome per system using the mean log loss."},
        "leakage": {"related_samples": "Deduplicate exact initial conditions and group perturbed variants by progenitor before splitting.",
                    "exposure": "The simulated outcomes are unpublished and unavailable to participants; only training outcomes are released.",
                    "preprocessing": "Fit normalization and feature selection on training systems only."},
        "protocol": {"restrictions": "There are no additional scientific restrictions."},
        "review": {"owner": "The organizer is responsible for scientific review.", "status": "Review is pending; the organizer will inspect the definitions and first evaluator results before release."},
        "plan": {"compute_budget": "Allow $50 of compute per credible attempt.", "token_budget": "Allow $10 of model tokens per credible attempt.",
                 "ownership": "The organizer owns the budget; the hard total limit is $60 per attempt.", "schedule": "Allow one week per attempt; there is no fixed launch date."},
        "entry": {"participants": "The challenge is open to all researchers.", "prerequisites": "Participants need basic orbital mechanics and machine learning knowledge."},
        "support": {"contact": "Participants can send task questions through the organizer support portal.",
                    "rules": "There is no competition deadline or financial prize.", "results": "The organizer will review measured results and provide written feedback before publication."},
    }
    c.onboarding_setup.update(project, {"competition_type": "prediction", "submissions_confirmed": True, "organizer_email": "owner@example.org"})
    updates = [update(field, list(values.values())) for field, values in facts.items()]
    requirements = [requirement(field, key, value) for field, values in facts.items() for key, value in values.items()]
    provider(monkeypatch, [scope(updates, requirements=requirements), draft("Planetary stability challenge")])
    c.submit_message(project, " ".join(value for values in facts.values() for value in values.values()), "complete-no-reference")
    state = project["conversation"]
    view = c.conversation_view(project)
    assert view["readiness"]["ready"]
    assert view["readiness"]["completed"] == view["readiness"]["total"] == 39
    assert view["readiness"]["optional_baseline"]["status"] == "not_provided"
    assert state["items"]["difficulty"]["status"] == state["items"]["trial"]["status"] == "missing"
    assert state["phase"] == "draft" and state["current_question"] is None
    assert "Challenge defined; technical preparation" in state["readme"]
    with pytest.raises(ValueError, match="already recorded"):
        c.continue_interview(project, "unneeded-continue")
    # A saved correction that could not be processed must close the build gate.
    provider(monkeypatch, [RuntimeError("Temporary provider failure")])
    c.submit_message(project, "Correction: the useful log-loss threshold should be 0.10.", "unprocessed-threshold")
    failed = c.conversation_view(project)
    assert failed["status"] == "error"
    assert not failed["readiness"]["ready"]
    assert failed["readiness"]["completed"] == 39
    assert failed["readiness"]["total"] == 40
    assert [item["requirement_id"] for item in failed["readiness"]["blockers"]] == ["pending_messages"]


def test_corrected_quote_copied_to_another_item_cannot_restore_completion(monkeypatch, project):
    original = "Stability means no collision or ejection for 5 Gyr."
    replacement = "Stability means no collision or ejection for 1 Gyr."
    provider(monkeypatch, [
        scope([update("data", original)], "data", "Which simulation source provides these labels?", requirements=[requirement("data", "outcomes", original), requirement("task", "outputs", original)]),
        scope([update("data", replacement, operation="correct", supersedes=[original])], "task", "What format should each prediction use?", requirements=[requirement("data", "outcomes", replacement)]),
        scope([], requirements=[requirement("task", "outputs", original)]),
    ])
    c.submit_message(project, original, "original-horizon")
    c.submit_message(project, "Correction: " + replacement, "correct-horizon")
    state = project["conversation"]
    assert original in state["_superseded_evidence"]
    assert original in state["items"]["task"]["value"]
    assert state["items"]["task"]["requirements"]["outputs"]["status"] == "missing"
    before = copy.deepcopy(state["items"])
    c.submit_message(project, "Please use the recorded task details.", "stale-reference")
    assert state["status"] == "error"
    assert state["items"] == before


def test_explicit_correction_can_restore_a_previously_replaced_decision(monkeypatch, project):
    original = "Stability means no collision or ejection for 5 Gyr."
    replacement = "Stability means no collision or ejection for 1 Gyr."
    provider(monkeypatch, [
        scope([update("data", original)], "data", "Which simulation source provides these labels?", requirements=[requirement("data", "outcomes", original)]),
        scope([update("data", replacement, operation="correct", supersedes=[original])], "data", "What permission applies to the simulation data?", requirements=[requirement("data", "outcomes", replacement)]),
        scope([update("data", original, operation="correct", supersedes=[replacement])], "task", "What format should each prediction use?", requirements=[requirement("data", "outcomes", original)]),
    ])
    c.submit_message(project, original, "first-horizon")
    c.submit_message(project, "Correction: " + replacement, "shorter-horizon")
    c.submit_message(project, "Correction: " + original, "restore-horizon")
    state = project["conversation"]
    assert state["status"] == "idle"
    assert state["items"]["data"]["requirements"]["outcomes"]["status"] == "recorded"
    assert state["items"]["data"]["value"] == original


def test_retired_budget_in_correction_sentence_is_not_the_new_budget(monkeypatch, project):
    original = "Compute costs $20 per attempt."
    correction = "Correction: change compute from $20 to $50 per attempt."
    provider(monkeypatch, [
        scope([update("plan", original)], "task", "What output should an attempt produce?", requirements=[
            requirement("plan", "compute_budget", original), requirement("deployment", "limits", "$20")]),
        scope([update("plan", correction, operation="correct", supersedes=["$20"])], requirements=[
            requirement("plan", "compute_budget", "$20")]),
    ])
    c.submit_message(project, original, "initial-compute")
    state = project["conversation"]
    before = copy.deepcopy(state["items"])
    c.submit_message(project, correction, "wrong-reassessment")
    assert state["status"] == "error"
    assert state["items"] == before


def test_actual_replacement_amount_can_complete_corrected_budget(monkeypatch, project):
    original = "Compute costs $20 per attempt."
    correction = "Correction: change compute from $20 to $50 per attempt."
    provider(monkeypatch, [
        scope([update("plan", original)], "task", "What output should an attempt produce?", requirements=[requirement("plan", "compute_budget", original)]),
        scope([update("plan", correction, operation="correct", supersedes=["$20"])], "data", "Where is the dataset available?", requirements=[requirement("plan", "compute_budget", "$50")]),
    ])
    c.submit_message(project, original, "initial-budget")
    c.submit_message(project, correction, "new-budget")
    state = project["conversation"]
    assert state["status"] == "idle"
    assert state["items"]["plan"]["requirements"]["compute_budget"]["value"] == "$50"
    assert state["items"]["plan"]["requirements"]["compute_budget"]["status"] == "recorded"


def test_short_requirement_excerpt_does_not_duplicate_fact_or_break_correction(monkeypatch, project):
    original = "Compute costs $20 per attempt. Alice owns the budget."
    correction = "Correction: change compute from $20 to $50 per attempt."
    provider(monkeypatch, [
        scope([update("plan", original)], "task", "What output should an attempt produce?", requirements=[
            requirement("plan", "compute_budget", "$20"),
            requirement("plan", "ownership", "Alice owns the budget.")]),
        scope([update("plan", correction, operation="correct", supersedes=["$20"])], "data", "Where is the dataset available?", requirements=[
            requirement("plan", "compute_budget", "$50"),
            requirement("plan", "ownership", "Alice owns the budget.")]),
    ])
    c.submit_message(project, original, "short-evidence")
    state = project["conversation"]
    assert state["items"]["plan"]["value"] == original
    assert state["items"]["plan"]["value"].count("$20") == 1
    assert state["items"]["plan"]["requirements"]["compute_budget"]["evidence"] == ["$20"]
    c.submit_message(project, correction, "correct-short-evidence")
    assert state["status"] == "idle"
    assert state["items"]["plan"]["value"] == original.replace("$20", "$50")
    assert state["items"]["plan"]["requirements"]["ownership"]["status"] == "recorded"
