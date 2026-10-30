"""Organizer decisions, selective evidence updates, and bounded clarification."""
import copy
import uuid

from fastapi.testclient import TestClient
import pytest

from autokaggle import conversation as c, readiness, workflow
from autokaggle.app import create_app
from autokaggle.store import Store
from autokaggle.tests.readiness_fixtures import complete_definition


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    store = Store(tmp_path / "scope")
    item = store.create("owner", "Scope study")
    complete_definition(item)
    item["conversation"]["_requirements_assessed"] = True
    return item


def resolution(identifier, mode="confirmed", detail="The organizer confirms the described scientific decision for this pilot."):
    return {"requirement_id": identifier, "mode": mode, "detail": detail}


def save(project, field="question", entries=None, summary="The pilot covers only the stated scientific question.", **kwargs):
    return c.set_scope(project, field, summary, entries or [], kwargs.pop("request_id", str(uuid.uuid4())), **kwargs)


def append(field, text, status="partial"):
    return {"field": field, "status": status, "operation": "append", "evidence": [text], "supersedes": [], "remaining_gap": "A related detail remains open."}


def test_append_unknown_and_partial_assessment_preserve_supported_criteria(project):
    state = project["conversation"]
    before = copy.deepcopy(state["items"]["question"]["requirements"])
    c._apply(state, [append("question", "I do not know another useful comparison.")], "new-info")
    c._apply_requirements(state, [{"field": "question", "id": "success", "status": "missing", "value": "", "evidence": [], "reason": "Not repeated in the last reply."}])
    assert state["items"]["question"]["requirements"] == before
    c._defer(state, "question", "I don't know", "unknown", "success")
    assert state["items"]["question"]["requirements"] == before
    assert readiness.item_understanding("question", state["items"]["question"])["score"] == 100


def test_correction_reopens_only_cited_requirement_and_dependents(project):
    state = project["conversation"]
    item = state["items"]["question"]
    old = item["requirements"]["success"]["value"]
    state["items"]["task"]["requirements"]["metric"]["evidence"] = [old]
    unaffected = copy.deepcopy(item["requirements"]["value"])
    change = {**append("question", "Use balanced accuracy of at least 0.80."), "operation": "correct", "supersedes": [old]}
    c._apply(state, [change], "correction")
    assert item["requirements"]["success"]["status"] == "missing"
    assert state["items"]["task"]["requirements"]["metric"]["status"] == "missing"
    assert item["requirements"]["value"] == unaffected


def test_scope_modes_are_distinct_and_removal_restores_underlying_gap(project):
    state = project["conversation"]
    item = state["items"]["question"]
    item["requirements"]["success"] = {"status": "missing", "reason": "Pilot threshold unknown."}
    source = copy.deepcopy(item["requirements"])
    view = save(project, entries=[resolution("success", "exception", "The exploratory pilot accepts no fixed success threshold; report scores without a success claim.")])
    criterion = next(x for x in view["checklist"] if x["id"] == "question")["requirements"][-1]
    assert criterion["status"] == "exception"
    assert view["readiness"]["exception"] == 1 and view["readiness"]["confirmed"] == 0
    assert item["requirements"] == source
    assert "Exception" in c._render(project) and "no fixed success threshold" in c._render(project)
    c.set_scope(project, "question", "", [], "remove-scope", True)
    assert item["requirements"] == source and "scope" not in item
    assert readiness.item_understanding("question", item)["completed"] == 2
    assert len(state["_scope_audit"]) == 2


@pytest.mark.parametrize("field,identifier", list(readiness.DELEGATION_POLICIES))
def test_delegation_has_fixed_safe_boundaries(project, field, identifier):
    item = project["conversation"]["items"][field]
    item["requirements"].pop(identifier)
    save(project, field, [resolution(identifier, "delegated", "Choose a simple implementation within the supplied platform and scientific constraints.")])
    delegated = readiness.scope_resolution(field, item, identifier)
    assert delegated["policy"] == readiness.DELEGATION_POLICIES[(field, identifier)]
    assert readiness.item_understanding(field, item)["delegated"] == 1
    assert identifier not in item["requirements"]


@pytest.mark.parametrize("field,identifier", [("data", "permission"), ("evaluation", "holdout"), ("task", "metric"), ("plan", "compute_budget")])
def test_scientific_decisions_cannot_be_delegated(project, field, identifier):
    before = copy.deepcopy(project)
    with pytest.raises(ValueError, match="cannot be delegated"):
        save(project, field, [resolution(identifier, "delegated")])
    assert project == before


@pytest.mark.parametrize("field", ["organizer", "competition", "submissions", "trial", "invented"])
def test_scope_cannot_accept_server_or_application_checks(project, field):
    with pytest.raises(ValueError, match="cannot be accepted"):
        save(project, field)


def test_scope_retry_is_idempotent_and_changed_id_payload_rejected(project):
    request = "stable-scope-request"
    save(project, entries=[resolution("success")], request_id=request)
    before = copy.deepcopy(project)
    save(project, entries=[resolution("success")], request_id=request)
    assert project == before
    with pytest.raises(ValueError):
        save(project, entries=[resolution("success", detail="A changed decision.")], request_id=request)
    assert project == before


def test_correction_of_scope_only_answer_stales_only_affected_resolution(project):
    state = project["conversation"]
    item = state["items"]["question"]
    item["requirements"] = {}
    item["value"] = ""
    old = "Useful success means balanced accuracy of at least 0.85."
    save(project, entries=[resolution("success", detail=old), resolution("value", detail="This reduces simulated laboratory costs.")])
    text = "Correction: useful success means balanced accuracy of at least 0.90."
    parsed = {"updates": [{**append("question", text), "operation": "correct", "supersedes": [old]}], "question_field": "", "question_text": ""}
    updates = c._validate_scope(parsed, text, state)
    c._apply(state, updates, "change-scope-only")
    assert text in item["value"] and old not in item["value"]
    assert readiness.scope_resolution("question", item, "success") is None
    assert readiness.scope_resolution("question", item, "value")["detail"] == "This reduces simulated laboratory costs."
    assert item["scope"]["stale"]
    assert state["_scope_audit"][-1]["action"] == "source_changed"


def test_append_does_not_stale_confirmed_scope(project):
    save(project, entries=[resolution("success")])
    before = copy.deepcopy(project["conversation"]["items"]["question"]["scope"])
    c._apply(project["conversation"], [append("question", "This is also useful for planning a later study.")], "additional-context")
    assert project["conversation"]["items"]["question"]["scope"] == before


def test_evidenced_conflict_reopens_only_related_decision(project):
    state = project["conversation"]
    item = state["items"]["methodology"]
    old = item["requirements"]["resources"]["value"]
    new = "Participants may use external training datasets and pretrained models."
    save(project, "methodology", [resolution("resources", detail=old)])
    parsed = {"updates": [append("methodology", new)], "requirements": [{"field": "methodology", "id": "resources", "status": "conflicting",
              "evidence": [old, new], "reason": "External resources were prohibited but are now allowed; confirm the policy."}], "question_field": "", "question_text": ""}
    updates = c._validate_scope(parsed, new, state)
    records = c._validate_requirements(parsed, new, state, updates)
    c._apply(state, updates, "contradiction")
    c._apply_requirements(state, records)
    assert item["requirements"]["resources"]["status"] == "conflicting"
    assert item["requirements"]["methods"]["status"] == "recorded"
    assert readiness.scope_resolution("methodology", item, "resources") is None
    replay = {**parsed, "updates": [], "requirements": [{**parsed["requirements"][0], "status": "recorded", "evidence": [old], "reason": ""}]}
    assert c._validate_requirements(replay, "A different reply.", state, []) == []


def test_conflict_without_prior_and_new_evidence_is_rejected(project):
    state = project["conversation"]
    parsed = {"requirements": [{"field": "question", "id": "success", "status": "conflicting", "evidence": ["A new statement."], "reason": "It might conflict."}]}
    with pytest.raises(ValueError, match="prior and new"):
        c._validate_requirements(parsed, "A new statement.", state, [])


def test_exception_and_delegation_cannot_become_scientific_evidence(project):
    state = project["conversation"]
    detail = "The organizer accepts an unresolved uncertainty estimate for this exploratory pilot."
    save(project, "evaluation", [resolution("uncertainty", "exception", detail)])
    parsed = {"requirements": [{"field": "question", "id": "value", "status": "recorded", "evidence": [detail], "reason": ""}]}
    with pytest.raises(ValueError, match="evidence was not"):
        c._validate_requirements(parsed, "A different answer.", state, [])


def test_two_unsuccessful_questions_stop_at_checkpoint_across_rounds(project):
    state = project["conversation"]
    state["items"]["question"]["requirements"].pop("success")
    suggestion = {"question_field": "question", "question_requirement_id": "success", "question_text": "What would count as useful progress?", "question_why": "The score needs a scientific interpretation."}
    c._advance(project, None, suggestion)
    assert state["current_question"]["requirement_id"] == "success"
    assert state["current_question"]["why"] == suggestion["question_why"]
    c._advance(project, None, {**suggestion, "question_text": "Which comparison should decide useful progress?"})
    assert state["_criterion_asks"]["question.success"] == 2
    c._advance(project, None, suggestion)
    assert state["current_question"] is None
    assert state["scope_checkpoint"]["requirement_id"] == "success"
    assert state["status"] == "idle" and state["_pending"] is None
    c.make_readme(project, "make-working-draft")
    c.continue_interview(project, "continue-round")
    assert state["current_question"] is None
    assert state["scope_checkpoint"]["requirement_id"] == "success"
    assert state["_criterion_asks"]["question.success"] == 2
    save(project, entries=[resolution("success", detail="Useful progress means balanced accuracy above0.75.")])
    assert state["scope_checkpoint"] is None


def test_legacy_question_migration_retains_prior_count(project):
    state = project["conversation"]
    state["items"]["question"]["requirements"].pop("success")
    state.pop("_criterion_asks")
    state["_asked"] = ["question", "question"]
    state["current_question"] = {"field": "question", "text": "What counts as useful progress?"}
    c.ensure_conversation(project)
    assert state["_criterion_asks"]["question.success"] == 2
    c._advance(project, None)
    assert state["scope_checkpoint"]["requirement_id"] == "success"


def test_nonnumeric_budget_does_not_reset_clarification_count(project):
    state = project["conversation"]
    state["items"]["plan"]["requirements"].pop("compute_budget")
    state["_criterion_asks"]["plan.compute_budget"] = 2
    c._apply_requirements(state, [{"field": "plan", "id": "compute_budget", "status": "recorded", "value": "A small compute budget.", "evidence": ["A small compute budget."], "reason": ""}])
    assert state["_criterion_asks"]["plan.compute_budget"] == 2


def test_scope_update_does_not_reask_a_deferred_detail(project):
    state = project["conversation"]
    state["items"]["question"]["requirements"]["scope"] = {"status": "deferred", "value": "unknown", "evidence": ["unknown"], "reason": "The organizer does not know."}
    state["items"]["question"]["requirements"].pop("success")
    state["current_question"] = {"field": "question", "requirement_id": "success", "text": "What is useful?"}
    save(project, entries=[])
    assert state["current_question"]["requirement_id"] == "success"


def test_temporary_scope_does_not_reset_exhausted_question_budget(project):
    state = project["conversation"]
    state["items"]["question"]["requirements"].pop("success")
    state["_criterion_asks"]["question.success"] = 2
    save(project, entries=[resolution("success", "exception", "No fixed threshold for this pilot.")])
    c.set_scope(project, "question", "", [], "remove-temporary-scope", True)
    assert state["_criterion_asks"]["question.success"] == 2
    assert state["current_question"] is None and state["scope_checkpoint"]["requirement_id"] == "success"


def test_scope_only_evidence_does_not_survive_removal_as_a_fact(project):
    state = project["conversation"]
    item = state["items"]["question"]
    item["requirements"] = {}
    item["value"] = ""
    state["items"]["task"]["requirements"].pop("metric")
    detail = "Success means balanced accuracy above 0.90 on the evaluation population."
    save(project, entries=[resolution("success", detail=detail)])
    parsed = {"requirements": [{"field": "question", "id": "success", "status": "recorded", "evidence": [detail], "reason": ""},
                               {"field": "task", "id": "metric", "status": "recorded", "evidence": [detail], "reason": ""}]}
    records = c._validate_requirements(parsed, "Please continue.", state, [])
    c._apply_requirements(state, records)
    assert "success" not in item["requirements"] and not item["value"]
    assert state["items"]["task"]["requirements"]["metric"]["scope_sources"]
    c.set_scope(project, "question", "", [], "remove-dependent-scope", True)
    assert readiness.item_understanding("question", item)["completed"] == 0
    assert state["items"]["task"]["requirements"]["metric"]["status"] == "missing"


def test_scope_restatement_keeps_independent_criterion_evidence(project):
    state = project["conversation"]
    original = copy.deepcopy(state["items"]["task"]["requirements"]["metric"])
    detail = "Useful progress means a balanced accuracy above 0.91."
    save(project, entries=[resolution("success", detail=detail)])
    parsed = {"requirements": [{"field": "task", "id": "metric", "status": "recorded", "evidence": [detail], "reason": ""}]}
    c._apply_requirements(state, c._validate_requirements(parsed, "Continue.", state, []))
    c.set_scope(project, "question", "", [], "remove-independent-scope", True)
    assert state["items"]["task"]["requirements"]["metric"] == original


def test_redundant_delegation_assessment_does_not_discard_explicit_correction(project):
    state = project["conversation"]
    item = state["items"]["methodology"]
    allowed = "External data and services are prohibited."
    delegated = "Choose a simple implementation within the fixed platform rules."
    save(project, "methodology", [resolution("methods", "delegated", delegated), resolution("resources", detail=allowed)])
    new = "Correction to the agreed resource policy: external datasets are now allowed, but external services remain prohibited."
    parsed = {"updates": [append("methodology", new)], "requirements": [
        {"field": "methodology", "id": "methods", "status": "recorded", "evidence": [delegated], "reason": ""},
        {"field": "methodology", "id": "resources", "status": "missing", "evidence": [new], "reason": "The accepted resource policy changed."}],
        "question_field": "", "question_text": ""}
    updates = c._validate_scope(parsed, new, state)
    records = c._validate_requirements(parsed, new, state, updates)
    c._apply(state, updates, "new-resource-decision")
    c._apply_requirements(state, records)
    assert readiness.scope_resolution("methodology", item, "methods")["mode"] == "delegated"
    assert readiness.scope_resolution("methodology", item, "resources") is None
    assert new in item["value"]


def test_rules_mode_method_restriction_reopens_only_methods(project):
    state = project["conversation"]
    item = state["items"]["methodology"]
    resources = copy.deepcopy(item["requirements"]["resources"])
    prior = item["value"]
    c.submit_message(project, "Methodology: require a linear reference model so we can compare each feature's effect.", "rules-method-change")
    assert item["requirements"]["methods"]["status"] == "missing"
    assert item["requirements"]["resources"] == resources
    assert prior in item["value"] and "linear reference model" in item["value"]


def test_rules_mode_resource_restriction_keeps_method_decision(project):
    state = project["conversation"]
    item = state["items"]["methodology"]
    methods = copy.deepcopy(item["requirements"]["methods"])
    c.submit_message(project, "Methodology: allow external datasets and pretrained models.", "rules-resources-change")
    assert item["requirements"]["resources"]["status"] == "missing"
    assert item["requirements"]["methods"] == methods


def test_data_outcome_question_does_not_request_source_or_upload(project):
    state = project["conversation"]
    state["items"]["data"]["requirements"].pop("outcomes")
    text = "What event defines an unstable planetary system?"
    c._advance(project, None, {"question_field": "data", "question_requirement_id": "outcomes", "question_text": text, "question_why": "The target label needs a definition."})
    assert state["current_question"]["text"] == text
    assert c.conversation_view(project)["current_question"]["text"] == text
    assert "Google Drive" not in state["messages"][-1]["content"]


def test_data_guidance_applies_only_to_available_source_question(project):
    state = project["conversation"]
    state["items"]["data"].update(value="", requirements={})
    prompt = "Where can we find the dataset?"
    assert "Google Drive" in c._data_link_question(state, prompt, "source")
    assert "200 MB" in c._data_link_question(state, prompt, "source")
    state["items"]["data"]["requirements"]["source"] = {"status": "deferred", "reason": "The source link is unavailable."}
    assert c._data_link_question(state, prompt, "source") == prompt


def test_api_scope_invalidates_legacy_package_once_and_preserves_owner_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    application = create_app(tmp_path / "api")
    try:
        with TestClient(application) as browser:
            identifier = browser.post("/api/projects", json={}).json()["id"]
            browser.patch(f"/api/projects/{identifier}/setup", json={"organizer_email": "owner@example.org"})
            store = application.state.store
            item = store.get(identifier, browser.cookies.get("autokaggle_owner"))
            item.update(prepared={"train_rows": 1}, _participant="old-participant-capability")
            store.save(item)
            archive = store.directory(identifier) / "researcher.zip"
            archive.write_bytes(b"old-archive")
            body = {"field": "question", "summary": "Pilot question.", "resolutions": [resolution("success", "exception", "The pilot accepts no fixed threshold.")], "request_id": "save-scope-request"}
            endpoint = f"/api/projects/{identifier}/conversation/scope"
            with TestClient(application) as outsider:
                assert outsider.post(endpoint, json=body).status_code == 404
            result = browser.post(endpoint, json=body)
            assert result.status_code == 200, result.text
            saved = store.get(identifier, browser.cookies.get("autokaggle_owner"))
            revision = saved["revision"]
            assert not saved["prepared"] and saved["_participant"] is None and not archive.exists()
            assert browser.post(endpoint, json=body).status_code == 200
            assert store.get(identifier, browser.cookies.get("autokaggle_owner"))["revision"] == revision
            assert browser.post(endpoint, json={**body, "request_id": "same-scope-new-id"}).status_code == 200
            assert store.get(identifier, browser.cookies.get("autokaggle_owner"))["revision"] == revision
    finally:
        application.state.pool.shutdown(wait=True)
