"""Gymnasium adapter for trusted local evaluation. No environment-specific metric."""
from __future__ import annotations
import importlib
import random


def evaluate(seed, manifest, contract):
    import gymnasium as gym
    fixed_horizon = contract.get("horizon_policy", "require_termination") == "fixed_horizon"
    max_steps = contract.get("max_steps")
    if fixed_horizon and (type(max_steps) is not int or max_steps <= 0):
        raise ValueError("A fixed evaluation horizon needs a positive max_steps value.")
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed % (2 ** 32))
    except ImportError:
        pass
    # Some environment packages register IDs on import.
    for package in contract.get("environment_imports", []):
        importlib.import_module(package)
    env = gym.make(contract["env_id"], **contract.get("environment_kwargs", {}))
    module, name = manifest["policy_loader"].split(":", 1)
    policy = getattr(importlib.import_module(module), name)(manifest["artifact_path"])
    score, steps, status, success, success_observed = 0.0, 0, "truncated", False, False
    end_reason = "step_limit"
    try:
        if contract.get("seed_method") == "core_disp":
            # Explicit dual RNG API is selected by the contract, not by environment name.
            env.unwrapped.seed(core=seed, disp=seed, reseed=False)
            reset = env.reset()
        else:
            reset = env.reset(seed=seed)
        observation = reset[0] if isinstance(reset, tuple) else reset
        if hasattr(policy, "reset"):
            policy.reset()
        while max_steps is None or steps < max_steps:
            observation, reward, terminated, truncated, info = env.step(policy.act(observation))
            score += float(reward)
            steps += 1
            success_key = contract.get("success_key") or "success"
            if success_key in info:
                success_observed = True
                success = success or bool(info[success_key])
            if terminated or truncated:
                if terminated:
                    status, end_reason = "completed", "terminated"
                elif fixed_horizon and steps == max_steps:
                    status, end_reason = "completed", "evaluation_horizon"
                else:
                    status, end_reason = "truncated", "environment_truncated"
                break
        else:
            if fixed_horizon and steps == max_steps:
                status, end_reason = "completed", "evaluation_horizon"
    finally:
        env.close()
    if status == "completed" and contract["metric"] == "success_rate" and not success_observed:
        raise ValueError("The environment did not report the configured success key.")
    return {"seed": seed, "status": status, "steps": steps, "end_reason": end_reason,
            "score": (float(success) if contract["metric"] == "success_rate" else score) if status == "completed" else None}
