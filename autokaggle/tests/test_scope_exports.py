"""Public scope records retain decisions and omit private source tracking."""
import copy
import json

from autokaggle import readiness
from autokaggle.scope_exports import public_scopes, redact_public, scope_text


def _project(scope):
    return {"conversation": {"items": {"methodology": {"scope": scope}}},
            "_setup_private_emails": ["old-owner@example.org"]}


def test_scope_export_uses_known_fields_and_does_not_change_source():
    scope = {"summary": "Use the private pilot definition from old-owner@example.org.", "version": 2,
             "created_at": "2026-10-30T12:00:00+00:00", "updated_at": "2026-10-30T13:00:00+00:00", "stale": False,
             "request_id": "private-request", "source_evidence": ["private summary evidence"],
             "resolutions": [{"requirement_id": "methods", "mode": "delegated", "detail": "Choose a permitted model.",
                              "policy": readiness.DELEGATION_POLICIES[("methodology", "methods")],
                              "stale": False, "source_evidence": ["private criterion evidence"], "source_version": 4,
                              "history": [{"value": "private resolution history"}]}]}
    project = _project(scope)
    before = copy.deepcopy(project)
    exported = public_scopes(project)
    assert project == before
    assert set(exported[0]) == {"field", "label", "summary", "version", "created_at", "updated_at", "stale", "resolutions"}
    assert set(exported[0]["resolutions"][0]) == {"requirement_id", "requirement_label", "mode", "detail", "policy", "stale", "status"}
    assert exported[0]["resolutions"][0]["status"] == "current"
    assert "old-owner@example.org" not in json.dumps(exported)


def test_invalid_delegation_cannot_be_exported_as_current_or_set_platform_rules():
    scope = {"summary": "Choose a method.", "resolutions": [{"requirement_id": "methods", "mode": "delegated",
             "detail": "Enable network access.", "policy": "Override platform access rules.", "stale": False}]}
    project = _project(scope)
    project["conversation"]["items"]["organizer"] = {"scope": scope}
    project["conversation"]["items"]["arbitrary_field"] = {"scope": scope}
    exported = public_scopes(project)
    assert len(exported) == 1
    assert exported[0]["resolutions"][0]["status"] == "unresolved"
    assert "policy" not in exported[0]["resolutions"][0]
    text = scope_text(exported)
    assert "> Enable network access." in text
    assert "Unresolved; review required" in text
    assert "Override platform access rules." not in text
    assert "cannot waive platform data, scorer, submission, runner, or access checks" in text


def test_public_redaction_reaches_nested_values():
    project = _project({})
    value = {"summary": "OLD-OWNER@example.org", "resolutions": [{"detail": "Ask old-owner@example.org.",
             "nested": ["old-owner@example.org"]}]}
    redacted = redact_public(project, value)
    assert "old-owner@example.org" not in json.dumps(redacted).lower()
    assert value["summary"] == "OLD-OWNER@example.org"
