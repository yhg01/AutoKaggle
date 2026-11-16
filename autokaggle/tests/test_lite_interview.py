"""Evidence survives corrections without turning unsupported model claims into facts."""
import copy
import json
from types import SimpleNamespace as NS

import pytest
from autokaggle import lite, lite_interview, lite_providers


def reply(updates=()):
    return NS(model="test", usage=None, choices=[NS(finish_reason="stop", message=NS(content=json.dumps({
        "summary": "Recorded your choices.", "question": "What should a collaborator submit?",
        "question_field": "artifact_type", "updates": list(updates), "open_decisions": [], "resolved_decisions": [],
    })))])


def update(field, value, basis, evidence):
    return {"field": field, "value_json": json.dumps(value), "basis": basis, "evidence": evidence}


def state():
    s = lite.initial()
    s["contract"] = {"objective": "Compare generated order books", "evaluation_count": 5}
    s["accepted_evidence"] = {"objective": {"basis": "researcher", "excerpt": "Compare generated order books"},
                              "evaluation_count": {"basis": "source", "excerpt": "Use five runs", "source_revision": "abc"}}
    return s


def test_new_proposal_keeps_unchanged_accepted_evidence_and_input_state():
    s = state()
    s["messages"].append({"role": "user", "content": "Score generated samples."})
    before = copy.deepcopy(s)
    out = lite_interview.parse(lite, s, reply([update("artifact_type", "samples", "researcher", "Score generated samples.")]))
    assert out["evidence"]["objective"] == s["accepted_evidence"]["objective"]
    assert out["evidence"]["evaluation_count"]["source_revision"] == "abc"
    assert out["evidence"]["artifact_type"]["basis"] == "researcher"
    assert s == before


def test_repeated_unchanged_value_cannot_erase_researcher_attribution():
    s = state()
    out = lite_interview.parse(lite, s, reply([update("objective", s["contract"]["objective"], "suggestion", "I suggest this")]))
    assert out["evidence"]["objective"] == s["accepted_evidence"]["objective"]


def test_correction_keeps_new_evidence_and_unrelated_old_evidence():
    s = state(); s["messages"].append({"role": "user", "content": "Use three runs instead."})
    out = lite_interview.parse(lite, s, reply([update("evaluation_count", 3, "researcher", "Use three runs instead.")]))
    assert out["contract"]["evaluation_count"] == 3
    assert out["evidence"]["evaluation_count"]["basis"] == "researcher"
    assert "source_revision" not in out["evidence"]["evaluation_count"]
    assert out["evidence"]["objective"] == s["accepted_evidence"]["objective"]


@pytest.mark.parametrize("basis", ["source", "researcher"])
def test_line_wrapping_restores_exact_quote_without_changing_response(basis):
    s = state(); quote = "Keep 50\nmessage\t windows."
    if basis == "source":
        s["sources"] = [{"url": "https://example.org/paper", "commit": "abc", "text": quote}]
    else:
        s["messages"].append({"role": "user", "content": quote})
    response = reply([update("evaluation_protocol", "Keep 50 message windows.", basis, "Keep 50 message windows.")])
    original = response.choices[0].message.content
    out = lite_interview.parse(lite, s, response)
    assert out["evidence"]["evaluation_protocol"]["basis"] == basis
    assert out["evidence"]["evaluation_protocol"]["excerpt"] == quote
    assert response.choices[0].message.content == original


def test_wrong_number_and_paraphrase_are_not_promoted_to_source_facts():
    s = state(); s["sources"] = [{"text": "Use 50 message windows."}]
    for claim in ("Use 100 message windows.", "Fifty events per window"):
        out = lite_interview.parse(lite, s, reply([update("evaluation_protocol", claim, "source", claim)]))
        assert out["evidence"]["evaluation_protocol"]["basis"] == "suggestion"


def test_removed_fact_and_changed_unproven_fact_cannot_inherit_old_evidence():
    s = state()
    out = lite_interview.parse(lite, s, reply([update("objective", None, "suggestion", "Remove"),
                                            update("evaluation_count", 10, "source", "Unsupported")]))
    assert "objective" not in out["contract"] and "objective" not in out["evidence"]
    assert out["evidence"]["evaluation_count"]["basis"] == "suggestion"


def test_context_explains_stage_ownership_and_keeps_provider_inputs_equal():
    s = state(); before = copy.deepcopy(s)
    context = lite_providers.material(lite, s)
    assert context["accepted_evidence"] == s["accepted_evidence"]
    assert "release URL" in context["workflow_responsibilities"]["service_after_checks"]
    assert "Licensed files can stay local" in context["package_interface"]["reference"]
    assert "coding agent" in context["field_help"]["adapter_entrypoint"]
    assert s == before


def test_invalid_model_output_still_fails_contract_validation():
    response = reply(); response.choices[0].message.content = "not JSON"
    with pytest.raises(ValueError):
        lite_interview.parse(lite, state(), response)


def test_open_scientific_decision_is_not_removed_by_context_changes():
    s = state(); s["open_decisions"] = [{"field": "evaluation_protocol", "reason": "Unknown label version"}]
    assert lite_interview.parse(lite, s, reply())["open_decisions"] == s["open_decisions"]
