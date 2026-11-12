"""Task-specific contracts keep a precise scalar scoring interface."""
import copy
import pytest
from autokaggle import lite, lite_build, lite_evaluator_cli
from autokaggle.tests.test_lite_build import contract

@pytest.mark.parametrize("kind,field,value,artifact", [
    ("optimization", "constraints", "x must be an integer in [0, 9]; reject all other values", "candidate"),
    ("forecasting", "temporal_policy", "Daily close only; next-day returns; fee 10bp per turnover; chronological test", "code"),
    ("generation", "generation_policy", "100 samples, fixed reference release, fixed sampler seeds", "samples"),
    ("custom", "metric_definition", "Compute residual energy in joules with tolerance 1e-8", "code"),
])
def test_task_requires_its_specific_protocol(kind, field, value, artifact):
    c = contract(task_kind=kind, artifact_type=artifact)
    assert not lite.ready(c)
    c[field] = value
    assert lite.ready(lite.clean_contract(c))


def test_custom_fitness_cannot_be_ready_without_formula_and_direction():
    c = contract(metric="custom", failure_policy="fail_run")
    assert not lite.ready(c)
    c.update(metric_name="Sharpe ratio", metric_definition="Mean daily net return / sample std * sqrt(252), zero variance is invalid", metric_direction="maximize")
    assert lite.ready(lite.clean_contract(c))
    with pytest.raises(ValueError, match="fail_run"):
        lite.clean_contract({**c, "failure_policy": "zero"})


def test_environment_accepts_code_but_not_candidate():
    assert lite.clean_contract({"task_kind": "environment", "artifact_type": "code"})
    with pytest.raises(ValueError):
        lite.clean_contract({"task_kind": "environment", "artifact_type": "candidate"})


def test_failure_diagnostics_do_not_repeat_execution(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("A failed seed must not execute again")
    monkeypatch.setattr(lite_evaluator_cli.subprocess, "run", forbidden)
    lite_evaluator_cli.explain({"seed": 1, "status": "failed"}, {}, {"timeout_seconds": 1})
    assert "No automatic retry" in capsys.readouterr().err


def test_deepseek_deployment_secret_and_model_settings(tmp_path, monkeypatch):
    from autokaggle.deploy import web, lite_web
    path = tmp_path / "model.env"
    path.write_text("DEEPSEEK_API_KEY=test-deepseek-key\n")
    monkeypatch.setattr(web, "PRIVATE_ENV", tmp_path / "full.env")
    monkeypatch.setattr(lite_web, "PRIVATE_ENV", tmp_path / "lite.env")
    monkeypatch.setattr(lite_web, "GITHUB_ENV", tmp_path / "absent.env")
    for module in (web, lite_web):
        private = module.private_settings(path)
        assert private["DEEPSEEK_API_KEY"] == private["OPENAI_API_KEY"] == "test-deepseek-key"
        assert "OPENROUTER_API_KEY" not in private
        resources = module.resources(b"source", "a" * 64, private, ["192.0.2.1"])
        config = next(item["data"] for item in resources if item["kind"] == "ConfigMap" and item["metadata"]["name"].endswith("-config"))
        assert config["OPENAI_BASE_URL"] == "https://api.deepseek.com"
        assert config["AUTOKAGGLE_MODEL"] == "deepseek-v4-pro"
        assert "DEEPSEEK_API_KEY" not in config


def test_invalid_model_shape_gets_one_bounded_repair(monkeypatch):
    import openai
    from autokaggle import lite_providers
    from autokaggle.tests.test_lite_build import FakeModel, REPLY
    monkeypatch.setattr(openai, "OpenAI", FakeModel)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    state=lite.initial()
    before=copy.deepcopy(state)
    FakeModel.calls,FakeModel.replies=[],['{"summary":"incomplete"}',REPLY]
    proposal=lite_providers.propose_deepseek(lite,state)
    assert len(FakeModel.calls)==2 and proposal['contract']['metric']=='accuracy'
    assert state==before
    FakeModel.calls,FakeModel.replies=[],['{}','{}']
    with pytest.raises(ValueError):lite_providers.propose_deepseek(lite,state)
    assert len(FakeModel.calls)==2 and state==before
