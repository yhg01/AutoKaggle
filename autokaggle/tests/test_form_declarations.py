"""A budget entered in the answer form also meets the interview's budget requirement."""
from fastapi.testclient import TestClient

from autokaggle import conversation as c, readiness
from autokaggle.app import create_app


def criterion(field, identifier):
    return next(item for item in readiness.REQUIREMENTS[field] if item["id"] == identifier)


def met(project, field, identifier):
    return readiness.criterion_result(field, project["conversation"]["items"][field], criterion(field, identifier))[0]


def edited(project, **answers):
    project["answers"].update(answers)
    c.sync_legacy_answers(project, manual_fields=answers.keys())
    return project


def fresh():
    project = {"title": "Form declaration fixture", "answers": {}, "_model_calls": 0}
    c.ensure_conversation(project)
    return project


def test_form_budget_meets_only_its_own_criterion():
    project = edited(fresh(), compute_budget="A100 x8 x24h")
    assert met(project, "plan", "compute_budget")
    assert not met(project, "plan", "token_budget")
    record = project["conversation"]["items"]["plan"]["requirements"]["compute_budget"]
    assert record["source"] == "form" and record["value"] == "A100 x8 x24h"


def test_cleared_or_unknown_form_budget_reopens_the_criterion():
    project = edited(fresh(), token_budget="2M tokens")
    assert met(project, "plan", "token_budget")
    edited(project, token_budget="")
    assert not met(project, "plan", "token_budget")
    edited(project, token_budget="unknown")
    assert not met(project, "plan", "token_budget")


def test_form_text_does_not_meet_criteria_that_need_assessment():
    project = edited(fresh(), objective="Predict plot yield.", success_criterion="Lower error than the cultivar mean.")
    assert not met(project, "question", "scope")
    assert not met(project, "task", "metric")


def test_answer_form_route_records_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOKAGGLE_MODE", "rules")
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        identifier = client.post("/api/projects", json={"title": "Form route fixture", "storage_accepted": True}).json()["id"]
        client.patch(f"/api/projects/{identifier}", json={"answers": {"compute_budget": "4 GPU-hours"}}).raise_for_status()
        view = client.get(f"/api/projects/{identifier}/conversation").json()
        plan = next(item for item in view["checklist"] if item["id"] == "plan")
        assert any(r["id"] == "compute_budget" and r["status"] == "recorded" for r in plan["requirements"])
