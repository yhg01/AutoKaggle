"""Scientific definition checks are separate from optional reference runs."""
import copy

import pytest

from autokaggle import readiness


def recorded(value="The researcher supplied a concrete decision."):
    return {"status": "recorded", "value": value, "evidence": [value], "reason": ""}


@pytest.fixture
def defined_state():
    items = {}
    for field, requirements in readiness.REQUIREMENTS.items():
        items[field] = {"status": "answered", "value": "Recorded researcher details.",
                        "requirements": {item["id"]: recorded() for item in requirements}}
    items["organizer"]["value"] = "organizer@example.org"
    items["competition"]["value"] = "Prediction competition: participants submit predictions for supplied test inputs."
    items["submissions"]["value"] = "5 submissions per day (confirmed)."
    items["plan"]["requirements"]["compute_budget"] = recorded("Compute budget: $100.")
    items["plan"]["requirements"]["token_budget"] = recorded("Model-token budget: $25.")
    return {"items": items}


def test_definition_is_the_approved_decision():
    assert readiness.DEFINITION == (
        "Within the agreed scope, another research agent can implement "
        "an attempt and interpret its score without inventing scientific assumptions."
    )


def test_all_fields_except_reference_and_reproduction_are_compulsory():
    assert set(readiness.REQUIREMENTS) - set(readiness.REQUIRED_FIELDS) == {"difficulty", "trial"}
    assert set(readiness.REQUIREMENTS) == set(readiness.FIELD_LABELS)
    for requirements in readiness.REQUIREMENTS.values():
        assert requirements
        assert len({item["id"] for item in requirements}) == len(requirements)
        assert all(item["label"] and item["description"] for item in requirements)


def test_optional_baseline_absence_does_not_block(defined_state):
    defined_state["items"]["difficulty"] = {"status": "deferred", "value": "No functional baseline is known."}
    defined_state["items"]["trial"] = {"status": "missing"}
    result = readiness.assess(defined_state)
    assert result["ready"]
    assert result["completed"] == result["total"]
    assert result["blockers"] == []
    assert result["optional_baseline"]["status"] == "not_provided"


@pytest.mark.parametrize("field", readiness.REQUIRED_FIELDS)
def test_each_required_dimension_blocks_if_missing(defined_state, field):
    defined_state["items"].pop(field)
    result = readiness.assess(defined_state)
    assert not result["ready"]
    assert {blocker["field"] for blocker in result["blockers"]} == {field}


def test_old_answered_flag_does_not_certify_scientific_requirements():
    result = readiness.item_understanding("question", {"status": "answered", "value": "Predict stable planets."})
    assert result["completed"] == result["score"] == 0
    assert result["total"] == 3
    assert result["required"] is True


def test_fraction_comes_from_complete_requirements():
    item = {"status": "partial", "requirements": {"scope": recorded(), "value": recorded()}}
    result = readiness.item_understanding("question", item)
    assert result["completed"] == 2
    assert result["total"] == 3
    assert result["score"] == 67
    assert result["detail"] == "2 of 3 requirements met."


@pytest.mark.parametrize("record", [
    {"status": "recorded", "value": "Complete", "evidence": []},
    {"status": "recorded", "value": "Complete", "evidence": [""]},
    {"status": "recorded", "value": "Complete", "evidence": "Complete"},
    {"status": "recorded", "value": "", "evidence": ["Complete"]},
    {"status": "recorded", "value": 10, "evidence": ["Complete"]},
    {"status": "answered", "value": "Complete", "evidence": ["Complete"]},
    {"status": "deferred", "value": "Maybe", "evidence": ["Maybe"]},
    None,
])
def test_invalid_or_unsupported_completion_stays_open(defined_state, record):
    defined_state["items"]["question"]["requirements"]["success"] = record
    result = readiness.assess(defined_state)
    assert not result["ready"]
    assert len(result["blockers"]) == 1
    assert result["blockers"][0]["requirement_id"] == "success"


def test_source_evidence_objects_are_accepted():
    item = {"requirements": {"scope": {"status": "recorded", "value": "Planet systems",
            "evidence": [{"message_id": "researcher-message", "quotes": ["Planet systems"]}]}}}
    assert readiness.item_understanding("question", item)["completed"] == 1


def test_optimization_can_explicitly_explain_no_labels(defined_state):
    defined_state["items"]["data"]["requirements"]["outcomes"] = {
        "status": "not_applicable", "value": "", "reason": "The objective is calculated from a feasible candidate, so there are no target labels.",
        "evidence": ["We calculate the objective directly from each feasible candidate; no labels are required."],
    }
    assert readiness.assess(defined_state)["ready"]


@pytest.mark.parametrize("change", [{"reason": ""}, {"evidence": []}, {"reason": None}])
def test_not_applicable_requires_a_grounded_reason(defined_state, change):
    record = {"status": "not_applicable", "reason": "No labels for this deterministic optimization task.", "evidence": ["No labels are needed."]}
    record.update(change)
    defined_state["items"]["data"]["requirements"]["outcomes"] = record
    assert not readiness.assess(defined_state)["ready"]


def test_compulsory_budget_cannot_be_waived(defined_state):
    defined_state["items"]["plan"]["requirements"]["token_budget"] = {
        "status": "not_applicable", "reason": "I do not know the token costs.", "evidence": ["I do not know the token costs."]}
    result = readiness.assess(defined_state)
    assert not result["ready"]
    assert result["blockers"][0]["requirement_id"] == "token_budget"


def test_compute_and_token_costs_are_separate_requirements(defined_state):
    defined_state["items"]["plan"]["requirements"]["compute_budget"] = recorded("Compute costs $25 to $50.")
    defined_state["items"]["plan"]["requirements"].pop("token_budget")
    result = readiness.assess(defined_state)
    assert not result["ready"]
    assert len(result["blockers"]) == 1
    assert result["blockers"][0]["requirement_id"] == "token_budget"


def test_model_requirement_cannot_replace_server_setup(defined_state):
    defined_state["items"]["organizer"].update(status="missing", value="")
    # The apparently complete model criterion is ignored for server-owned fields.
    assert defined_state["items"]["organizer"]["requirements"]["contact"]["status"] == "recorded"
    assert not readiness.assess(defined_state)["ready"]


@pytest.mark.parametrize("field,value", [
    ("organizer", "not-an-email"),
    ("organizer", "person@example.org\nBcc: other@example.org"),
    ("competition", "Probably prediction or code."),
    ("submissions", "5 submissions per day (default or proposed; not confirmed)."),
    ("submissions", "0 submissions per day (confirmed)."),
    ("submissions", "1001 submissions per day (confirmed)."),
])
def test_invalid_server_values_do_not_pass(defined_state, field, value):
    defined_state["items"][field]["value"] = value
    assert not readiness.assess(defined_state)["ready"]


def test_human_cannot_assert_application_execution_complete():
    item = {"status": "answered", "value": "I ran the baseline.", "requirements": {"execution": recorded("I ran the baseline.")}}
    result = readiness.item_understanding("trial", item)
    assert result["completed"] == 0
    assert result["required"] is False
    assert result["score"] is None
    assert result["label"] == "Optional system check"


def test_missing_state_fails_closed_and_does_not_mutate_input(defined_state):
    original = copy.deepcopy(defined_state)
    readiness.assess(defined_state)
    assert defined_state == original
    for state in (None, {}, {"items": None}, {"items": {"question": None}}):
        result = readiness.assess(state)
        assert not result["ready"]
        assert result["completed"] == 0
        assert len(result["blockers"]) == result["total"]


def test_assessment_does_not_include_private_organizer_address(defined_state):
    result = readiness.assess(defined_state)
    assert "organizer@example.org" not in str(result)


def test_unrecognized_requirement_cannot_increase_progress():
    item = {"requirements": {"invented_complete_requirement": recorded()}}
    result = readiness.item_understanding("question", item)
    assert result["completed"] == 0
    assert result["total"] == 3


@pytest.mark.parametrize("value", ["unknown", "Unknown.", "TBD", "I don't know.", "not yet known"])
def test_unknown_only_answers_do_not_complete_requirement(defined_state, value):
    defined_state["items"]["question"]["requirements"]["success"] = recorded(value)
    result = readiness.assess(defined_state)
    assert not result["ready"]
    assert len(result["blockers"]) == 1


@pytest.mark.parametrize("value", ["$0", "0 dollars", "$20 to $50", "USD 100", "100 USD", "$1,000.00"])
def test_numeric_dollar_budgets_are_accepted(defined_state, value):
    defined_state["items"]["plan"]["requirements"]["compute_budget"] = recorded(value)
    assert readiness.assess(defined_state)["ready"]


@pytest.mark.parametrize("value", ["A small amount", "20", "20 tokens", "Unknown", "GBP 20"])
def test_budget_needs_a_dollar_amount(defined_state, value):
    defined_state["items"]["plan"]["requirements"]["token_budget"] = recorded(value)
    result = readiness.assess(defined_state)
    assert not result["ready"]
    assert result["blockers"][0]["requirement_id"] == "token_budget"


def test_budget_can_keep_numeric_amount_in_its_source_excerpt(defined_state):
    defined_state["items"]["plan"]["requirements"]["token_budget"] = {
        "status": "recorded", "value": "The estimated token budget is confirmed.",
        "evidence": [{"quotes": ["We can spend $20 on tokens per attempt."]}],
    }
    assert readiness.assess(defined_state)["ready"]


def test_unknown_reason_cannot_make_labels_not_applicable(defined_state):
    defined_state["items"]["data"]["requirements"]["outcomes"] = {
        "status": "not_applicable", "reason": "Unknown", "evidence": ["Unknown"],
    }
    assert not readiness.assess(defined_state)["ready"]


def test_manual_bypass_resolves_only_its_requirement_without_changing_evidence(defined_state):
    item = defined_state["items"]["question"]
    item["requirements"]["success"] = {"status": "missing", "reason": "The estimate is still uncertain."}
    original = copy.deepcopy(item["requirements"])
    item["bypasses"] = {"success": {"reason": "The team accepts an exploratory pilot without a fixed threshold.",
                                    "created_at": "2026-10-30T12:00:00+00:00", "updated_at": "2026-10-30T12:00:00+00:00"}}
    result = readiness.assess(defined_state)
    assert result["ready"] and result["completed"] == result["total"]
    assert result["bypassed"] == 1
    assert result["bypasses"][0]["requirement_id"] == "success"
    progress = readiness.item_understanding("question", item)
    assert progress["score"] == 100 and progress["bypassed"] == 1
    assert progress["label"] == "Resolved with bypass"
    assert item["requirements"] == original


@pytest.mark.parametrize("record", [None, {}, {"reason": ""}, {"reason": "  "}, {"reason": 3}, {"reason": "x" * 2001}])
def test_invalid_manual_bypass_cannot_resolve_a_gap(defined_state, record):
    item = defined_state["items"]["question"]
    item["requirements"].pop("success")
    item["bypasses"] = {"success": record}
    result = readiness.assess(defined_state)
    assert not result["ready"] and result["bypassed"] == 0


@pytest.mark.parametrize("field,identifier", [("organizer", "contact"), ("competition", "choice"),
                                          ("submissions", "allowance"), ("trial", "execution"),
                                          ("difficulty", "reference"), ("question", "invented")])
def test_manual_bypass_cannot_override_validated_settings_or_execution(defined_state, field, identifier):
    item = defined_state["items"][field]
    item.update(status="missing", value="", requirements={}, bypasses={identifier: {"reason": "An attempted exception."}})
    assert not readiness.can_bypass(field, identifier)
    assert readiness.item_understanding(field, item)["completed"] == 0
    assert readiness.assess(defined_state)["bypassed"] == 0


def test_pending_answer_blocks_even_if_all_scientific_gaps_are_bypassed(defined_state):
    item = defined_state["items"]["question"]
    item["requirements"].pop("success")
    item["bypasses"] = {"success": {"reason": "The organizer accepts the exploratory scope."}}
    defined_state["_unprocessed"] = [{"text": "An unassessed correction."}]
    result = readiness.assess(defined_state)
    assert not result["ready"]
    assert result["bypassed"] == 1
    assert result["blockers"][0]["requirement_id"] == "pending_messages"
