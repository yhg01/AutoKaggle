from __future__ import annotations

import copy
import json

import pytest

from autokaggle import conversation as c
from autokaggle import onboarding_setup as setup


@pytest.fixture
def project(monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    return {"title": "New challenge", "_model_calls": 0}


def test_defaults_do_not_choose_format_or_confirm_quota(project):
    state = c.ensure_conversation(project)
    assert setup.get(project) == {"competition_type": None, "daily_submission_limit": 5,
                                   "submissions_confirmed": False, "organizer_email": ""}
    assert state["items"]["competition"]["status"] == "missing"
    assert state["items"]["submissions"]["status"] == "missing"
    assert "Confirm 5" in state["items"]["submissions"]["gap"]
    first = setup.defaults()
    first["daily_submission_limit"] = 8
    assert setup.defaults()["daily_submission_limit"] == 5


@pytest.mark.parametrize("changes", [
    {"competition_type": "automatic"}, {"competition_type": True},
    {"daily_submission_limit": 0}, {"daily_submission_limit": 1001},
    {"daily_submission_limit": True}, {"daily_submission_limit": 5.0},
    {"daily_submission_limit": "5"}, {"submissions_confirmed": "yes"},
    {"organizer_email": None}, {"organizer_email": "not-an-email"},
    {"organizer_email": "Alice <alice@example.org>"},
    {"organizer_email": "alice@example.org\r\nBcc: bob@example.org"},
    {"organizer_email": "alice..smith@example.org"},
    {"organizer_email": "alice@example..org"},
    {"organizer_email": "alice@-example.org"},
    {"competition_type": "code", "organizer_email": "bad"},
    {"email_sent": True}, [], None,
])
def test_invalid_patch_has_no_partial_writes(project, changes):
    before = copy.deepcopy(project)
    with pytest.raises(ValueError):
        setup.update(project, changes)
    assert project == before


def test_explicit_form_values_sync_and_preserve_source_evidence(project):
    result = setup.update(project, {"competition_type": "code", "daily_submission_limit": 7,
                                    "submissions_confirmed": True, "organizer_email": "Alice+research@EXAMPLE.ORG"})
    state = c.ensure_conversation(project)
    assert result["organizer_email"] == "Alice+research@example.org"
    assert all(state["items"][key]["status"] == "answered" for key in setup.ITEM_FIELDS)
    assert state["items"]["organizer"]["value"] == result["organizer_email"]
    record = state["items"]["submissions"]["evidence"][-1]
    assert record["source"] == "form"
    assert json.loads(record["quotes"][0]) == {"daily_submission_limit": 7, "submissions_confirmed": True}
    assert "organizer_email" not in setup.get(project, include_private=False)
    assert project["_model_calls"] == 0


def test_limit_change_requires_new_confirmation_and_invalidates_draft(project):
    setup.update(project, {"submissions_confirmed": True})
    c.make_readme(project, "draft-1")
    assert project["conversation"]["readme"]
    setup.update(project, {"daily_submission_limit": 8})
    state = c.ensure_conversation(project)
    assert not setup.get(project)["submissions_confirmed"]
    assert state["items"]["submissions"]["status"] == "missing"
    assert state["readme"] is None
    setup.update(project, {"submissions_confirmed": True})
    assert state["items"]["submissions"]["status"] == "answered"


def test_form_update_clears_already_answered_active_question(project):
    state = c.ensure_conversation(project)
    state.update(current_question={"field": "competition", "text": "Choose a format."}, followups=1)
    state["_asked"].append("competition")
    setup.update(project, {"competition_type": "prediction"})
    assert state["current_question"] is None
    assert state["followups"] == 1
    assert "competition" not in c._eligible(state)


def test_old_conversation_migrates_without_losing_answers_or_retry_state(project):
    c.submit_message(project, "Our existing scientific question", "start")
    c.make_readme(project, "draft")
    state = project["conversation"]
    for key in setup.ITEM_FIELDS:
        state["items"].pop(key)
    project.pop("setup")
    state["readme"] = "# Earlier draft"
    state.update(status="error", can_retry=True, _pending={"kind": "draft"})
    preserved = {key: copy.deepcopy(state[key]) for key in ("messages", "_requests", "followups", "_pending", "_history")}
    old_question = copy.deepcopy(state["items"]["question"])
    migrated = c.ensure_conversation(project)
    assert len(migrated["items"]) == 17
    assert migrated["items"]["question"] == old_question
    assert all(migrated[key] == value for key, value in preserved.items())
    assert migrated["status"] == "error" and migrated["can_retry"]
    assert "Required challenge artifacts" in migrated["readme"]
    snapshot = copy.deepcopy(project)
    c.ensure_conversation(project)
    assert project == snapshot


@pytest.mark.parametrize("text,expected", [
    ("Competition: code", {"competition_type": "code"}),
    ("Competition type: prediction", {"competition_type": "prediction"}),
    ("We choose a code competition.", {"competition_type": "code"}),
    ("Let's use a prediction file.", {"competition_type": "prediction"}),
    ("Code submissions", {"competition_type": "code"}),
    ("Daily submissions: 12", {"daily_submission_limit": 12, "submissions_confirmed": True}),
    ("Organizer email: owner@example.org", {"organizer_email": "owner@example.org"}),
    ("The organizer review email is owner@example.org.", {"organizer_email": "owner@example.org"}),
    ("My email is owner@example.org.", {"organizer_email": "owner@example.org"}),
    ("We confirm five submissions per team per UTC day.", {"daily_submission_limit": 5, "submissions_confirmed": True}),
    ("Daily submissions: ten per team per UTC day", {"daily_submission_limit": 10, "submissions_confirmed": True}),
])
def test_explicit_chat_setting_is_recorded_without_a_model(project, text, expected):
    c.submit_message(project, text, "message")
    assert all(setup.get(project)[key] == value for key, value in expected.items())
    assert project["_model_calls"] == 0
    records = [record for key in setup.ITEM_FIELDS for record in project["conversation"]["items"][key]["evidence"]]
    assert any(text in record["quotes"] and record["source"] == "chat" for record in records)


def test_short_answer_and_confirmation_use_active_setting(project):
    state = c.ensure_conversation(project)
    state["current_question"] = {"field": "competition", "text": "Which format?"}
    c.submit_message(project, "code", "choice")
    state["current_question"] = {"field": "submissions", "text": "Confirm 5 per day?"}
    c.submit_message(project, "Yes", "confirm")
    assert setup.get(project)["competition_type"] == "code"
    assert setup.get(project)["submissions_confirmed"]


@pytest.mark.parametrize("text", ["We might choose code someday.", "The model code predicts 5 targets.",
                                    "We have 5 samples per day.", "Competition: code\nCompetition: prediction"])
def test_uncertain_or_conflicting_prose_is_not_a_setting(project, text):
    changes, _evidence, complete = setup.extract_message(project, text)
    assert changes == {} and not complete


def test_original_live_brief_forms_extract_all_three_settings_without_model_inference(project):
    text = ("Predict material stability before stress testing. "
            "Choose code submissions, five submissions per team per UTC day. "
            "The organizer review email is owner@example.org. "
            "The organizer will inspect the first measured trial this week before any release.")
    changes, evidence, complete = setup.extract_message(project, text)
    assert changes == {"competition_type": "code", "daily_submission_limit": 5,
                       "submissions_confirmed": True, "organizer_email": "owner@example.org"}
    assert complete is False
    assert evidence["competition"] == ["Choose code submissions, five submissions per team per UTC day."]
    assert evidence["submissions"] == evidence["competition"]
    assert evidence["organizer"] == ["The organizer review email is owner@example.org."]
    assert all(quote in text for quotes in evidence.values() for quote in quotes)


def test_conversational_choices_need_no_form_or_special_field_labels(project):
    text = "Let's use code submissions and keep five per day. My email is owner@example.org."
    changes, evidence, complete = setup.extract_message(project, text)
    assert changes == {"competition_type": "code", "daily_submission_limit": 5,
                       "submissions_confirmed": True, "organizer_email": "owner@example.org"}
    assert complete
    assert all(quote in text for quotes in evidence.values() for quote in quotes)
    assert setup.redact_private(project, text).endswith("My email is [private organizer email].")


@pytest.mark.parametrize("text", [
    "Do not choose code submissions, five submissions per team per UTC day.",
    "If approved, choose code submissions, five submissions per team per UTC day.",
    "Choose code submissions, five submissions per team per UTC day unless we change our mind.",
    "Choose code submissions, five or ten submissions per team per UTC day.",
    "Choose code or prediction submissions, five submissions per team per UTC day.",
    "We might confirm five submissions per team per UTC day.",
    "Five submissions per team per UTC day might be enough.",
    "The organizer review email is not owner@example.org.",
    "The organizer review email is owner@example.org or other@example.org.",
    "The organizer review email is owner@example.org if approved.",
    "The organizer review email might be owner@example.org.",
])
def test_new_explicit_prose_forms_reject_negation_conditions_and_alternatives(project, text):
    changes, _evidence, complete = setup.extract_message(project, text)
    assert changes == {} and complete is False


def test_combined_choices_do_not_hide_conflicts_in_later_sentences(project):
    changes, evidence, complete = setup.extract_message(project,
        "Choose code submissions, five submissions per team per UTC day. "
        "Choose prediction submissions, ten submissions per team per UTC day.")
    assert changes == {} and evidence == {} and complete is False


def test_combined_choice_and_quota_can_be_saved_without_a_model(project):
    c.submit_message(project, "Choose code submissions, five submissions per team per UTC day.", "settings")
    state = project["conversation"]
    assert state["items"]["competition"]["status"] == "answered"
    assert state["items"]["submissions"]["status"] == "answered"
    assert project["_model_calls"] == 0


def test_model_cannot_override_explicit_settings(project):
    state = c.ensure_conversation(project)
    malicious = {"updates": [{"field": "competition", "status": "answered", "operation": "append",
                               "evidence": ["code"], "supersedes": [], "remaining_gap": ""}],
                 "question_field": "", "question_text": ""}
    with pytest.raises(ValueError):
        c._validate_scope(malicious, "We might choose code someday.", state)
    assert setup.get(project)["competition_type"] is None


def test_private_email_redacted_from_every_readme_section_and_history(project):
    first, second = "owner&lab@example.org", "new-owner@example.org"
    setup.update(project, {"organizer_email": first, "competition_type": "code"})
    setup.update(project, {"organizer_email": second})
    state = c.ensure_conversation(project)
    project["title"] = "Study by " + first
    state["items"]["question"].update(value=f"Contact {first} or {second}", status="answered", gap="")
    state["_unprocessed"] = [{"message_id": "failed", "text": f"Failed message: {first}"}]
    state["_draft_meta"] = {"intro": f"Organizer {second}", "next_actions": [f"Ask {first} to review."]}
    readme = c._render(project)
    assert first not in readme and "owner&amp;lab@example.org" not in readme and second not in readme
    assert "### Organizer email" not in readme
    assert "[private organizer email]" in readme
    assert c.conversation_view(project)["setup"]["organizer_email"] == second
    assert state["items"]["organizer"]["evidence"][0]["source"] == "form"


@pytest.mark.parametrize("kind,phrase", [("prediction", "test inputs without answer labels"), ("code", "representative test examples")])
def test_readme_describes_required_artifacts_without_claiming_execution(project, kind, phrase):
    setup.update(project, {"competition_type": kind, "daily_submission_limit": 3, "submissions_confirmed": True})
    c.make_readme(project, "draft")
    text = project["conversation"]["readme"]
    for required in ("input/output contract", "file hashes", "metric version", "dependencies", "CPU, GPU, time, and RAM", "model-token budgets in dollars", "first complete submission-and-scoring trial", "before publication", phrase):
        assert required in text
    assert "Daily submission limit: 3 (confirmed)" in text
    assert "does not establish that these files exist or that an evaluator has run" in text
    assert "email delivery, and publication remain planned" in text


def test_deferred_setting_remains_deferred_and_does_not_repeat(project):
    state = c.ensure_conversation(project)
    state["current_question"] = {"field": "competition", "text": "Which format?"}
    state["_asked"].append("competition")
    c.submit_message(project, "unknown", "unknown")
    assert state["items"]["competition"]["status"] == "deferred"
    assert "competition" not in c._eligible(state)
    assert setup.get(project)["competition_type"] is None


@pytest.mark.parametrize("ending", [".", ",", ";", "!"])
def test_chat_email_sentence_punctuation_is_accepted_and_remains_private(project, ending):
    address = "owner+research@example.org"
    c.submit_message(project, f"Organizer email: {address}{ending}", "email")
    assert setup.get(project)["organizer_email"] == address
    assert project["conversation"]["items"]["organizer"]["evidence"][-1]["quotes"] == [f"Organizer email: {address}{ending}"]
    c.make_readme(project, "draft")
    assert address not in project["conversation"]["readme"]


def test_organizer_addresses_remain_private_when_extraction_fails(project, monkeypatch):
    monkeypatch.setattr(c.advisor, "configured", lambda: True)

    def fail(*_args, **_kwargs):
        raise ValueError("Bad model response")

    monkeypatch.setattr(c, "_provider", fail)
    text = "Our organizer's email is owner@example.org. We want to predict stability."
    c.submit_message(project, text, "failed-message")
    assert project["conversation"]["status"] == "error"
    assert setup.get(project)["organizer_email"] == "owner@example.org"  # Explicit prose is saved before the model call.
    c.make_readme(project, "draft-after-failure")
    assert "Messages awaiting manual review" in project["conversation"]["readme"]
    assert "owner@example.org" not in project["conversation"]["readme"]
    assert text in [message["content"] for message in project["conversation"]["messages"]]


def test_migration_redacts_old_unparsed_organizer_messages(project):
    state = c.ensure_conversation(project)
    state["messages"].append({"id": "old-message", "role": "user", "content": "Organizer email: old@example.org."})
    state["readme"] = "# Draft\nOrganizer email: old@example.org."
    state.pop("_setup_privacy_migrated")
    assert "old@example.org" not in c.conversation_view(project)["readme"]
    setup.update(project, {"organizer_email": "new@example.org"})
    assert setup.redact_private(project, "old@example.org and new@example.org") == "[private organizer email] and [private organizer email]"


def test_multiword_setup_label_can_be_deferred(project):
    c.submit_message(project, "Organizer email: unknown", "deferred-email")
    assert project["conversation"]["items"]["organizer"]["status"] == "deferred"
    assert "organizer" not in c._eligible(project["conversation"])
