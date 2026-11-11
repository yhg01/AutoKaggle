"""A declared evaluation horizon can finish a continuing RL environment."""
import sys
from types import SimpleNamespace

import pytest

from autokaggle.lite_gym_adapter import evaluate


def setup_environment(monkeypatch, *, terminal=None, truncate=None, success=False):
    class Environment:
        steps = 0
        closed = False

        def reset(self, **kwargs):
            self.steps = 0
            self.seed = kwargs["seed"]
            return 0, {}

        def step(self, action):
            self.steps += 1
            info = {"goal": True} if success else {}
            return 0, -2.0, self.steps == terminal, self.steps == truncate, info

        def close(self):
            self.closed = True

    env = Environment()
    monkeypatch.setitem(sys.modules, "gymnasium", SimpleNamespace(make=lambda *a, **k: env))
    monkeypatch.setitem(sys.modules, "horizon_policy_fixture", SimpleNamespace(
        load=lambda path: SimpleNamespace(act=lambda observation: 0)))
    return env


def run_case(**changes):
    contract = {"env_id": "GenericContinuing-v0", "metric": "mean_score", "max_steps": 4,
                "horizon_policy": "fixed_horizon", "seed_method": "reset", **changes}
    return evaluate(42, {"policy_loader": "horizon_policy_fixture:load", "artifact_path": "unused"}, contract)


@pytest.mark.parametrize("truncate", [None, 4])
def test_declared_horizon_scores_continuing_return(monkeypatch, truncate):
    env = setup_environment(monkeypatch, truncate=truncate)
    result = run_case()
    assert result == {"seed": 42, "status": "completed", "steps": 4,
                      "end_reason": "evaluation_horizon", "score": -8.0}
    assert env.seed == 42 and env.closed


def test_early_terminal_scores_its_actual_return(monkeypatch):
    env = setup_environment(monkeypatch, terminal=2)
    result = run_case()
    assert result["status"] == "completed" and result["score"] == -4.0
    assert result["steps"] == 2 and result["end_reason"] == "terminated"
    assert env.closed


def test_early_truncation_cannot_complete_declared_horizon(monkeypatch):
    env = setup_environment(monkeypatch, truncate=2)
    result = run_case()
    assert result["status"] == "truncated" and result["score"] is None
    assert result["steps"] == 2 and result["end_reason"] == "environment_truncated"
    assert env.closed


@pytest.mark.parametrize("truncate", [None, 4])
def test_termination_policy_preserves_incomplete_horizon(monkeypatch, truncate):
    setup_environment(monkeypatch, truncate=truncate)
    result = run_case(horizon_policy="require_termination")
    assert result["status"] == "truncated" and result["score"] is None


def test_fixed_horizon_requires_observed_success_for_success_rate(monkeypatch):
    env = setup_environment(monkeypatch, truncate=4)
    with pytest.raises(ValueError, match="success key"):
        run_case(metric="success_rate", success_key="goal")
    assert env.closed
    setup_environment(monkeypatch, truncate=4, success=True)
    assert run_case(metric="success_rate", success_key="goal")["score"] == 1.0


@pytest.mark.parametrize("max_steps", [None, 0, -1, True])
def test_fixed_horizon_needs_positive_integer_limit(monkeypatch, max_steps):
    setup_environment(monkeypatch)
    with pytest.raises(ValueError, match="positive max_steps"):
        run_case(max_steps=max_steps)
