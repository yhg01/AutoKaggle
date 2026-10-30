"""Dataset invariants, leakage cases, and bounded baseline checks."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from autokaggle.core import datasets


def save(tmp_path: Path, frame: pd.DataFrame, name: str = "input.csv") -> Path:
    path = tmp_path / name
    frame.to_csv(path, index=False)
    return path


def sample(n: int = 300, task: str = "classification") -> pd.DataFrame:
    rng = np.random.default_rng(4321)
    x, noise = rng.normal(size=n), rng.normal(size=n)
    y = ((x + noise * 0.6) > 0).astype(int) if task == "classification" else x * 2 + noise
    return pd.DataFrame({"row_id": np.arange(n), "signal": x, "category": rng.choice(["a", "b", "c"], n), "target": y})


def design(**updates) -> dict:
    result = {"target": "target", "task": "classification", "metric": "accuracy", "split": "random", "exclude_columns": ["row_id"], "test_fraction": 0.2}
    result.update(updates)
    return result


def blockers(analysis: dict) -> set[str]:
    return {check["id"] for check in analysis["checks"] if check["severity"] == "blocker"}


def test_profile_has_counts_without_cell_values(tmp_path):
    frame = sample()
    frame.loc[:20, "signal"] = np.nan
    result = datasets.profile_csv(save(tmp_path, frame))
    assert result["rows"] == 300
    assert result["size_bytes"] > 0
    assert next(item for item in result["columns"] if item["name"] == "signal")["missing"] == 21
    assert all(set(column) == {"name", "dtype", "missing", "unique"} for column in result["columns"])


@pytest.mark.parametrize("contents", ["", "x,x\n1,2\n", "x, x \n1,2\n", "x,\n1,2\n", "x,y\n", "x,y\n1,2,3\n", "x,y\n1\n", 'x,y\n"unterminated,2\n', "x,y\n1,\x00\n", "x,\x00y\n1,2\n"])
def test_reject_invalid_csv(tmp_path, contents):
    path = tmp_path / "bad.csv"
    path.write_text(contents)
    with pytest.raises(ValueError):
        datasets.profile_csv(path)


def test_reject_non_utf8(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes(b"x,y\n1,\xff\n")
    with pytest.raises(ValueError, match="UTF-8"):
        datasets.profile_csv(path)


@pytest.mark.parametrize("limit,value,message", [("MAX_BYTES", 2, "200 MB"), ("MAX_ROWS", 1, "rows"), ("MAX_COLUMNS", 1, "columns"), ("MAX_CELLS", 1, "cells")])
def test_input_bounds(tmp_path, monkeypatch, limit, value, message):
    path = save(tmp_path, sample(30))
    monkeypatch.setattr(datasets, limit, value)
    with pytest.raises(ValueError, match=message):
        datasets.profile_csv(path)


@pytest.mark.parametrize("limit,accepted", [("MAX_BYTES", 8), ("MAX_ROWS", 1), ("MAX_COLUMNS", 2), ("MAX_CELLS", 2)])
def test_csv_limit_is_inclusive(tmp_path, monkeypatch, limit, accepted):
    path = tmp_path / "boundary.csv"
    path.write_bytes(b"x,y\n1,2\n")
    monkeypatch.setattr(datasets, limit, accepted)
    assert datasets.profile_csv(path)["rows"] == 1
    monkeypatch.setattr(datasets, limit, accepted - 1)
    with pytest.raises(ValueError):
        datasets.profile_csv(path)


@pytest.mark.parametrize("metric", ["accuracy", "balanced_accuracy", "roc_auc"])
def test_classification_baselines(tmp_path, metric):
    result = datasets.analyze_dataset(save(tmp_path, sample()), design(metric=metric), {}, 83)
    assert not blockers(result)
    assert result["split"]["train_rows"] == 240
    assert result["split"]["test_rows"] == 60
    assert result["baseline"]["status"] == "complete"
    assert result["baseline"]["validation_rows"] == 48
    assert 0 <= result["baseline"]["score"] <= 1
    assert "final test set was not fitted or scored" in result["baseline"]["detail"]


@pytest.mark.parametrize("metric", ["rmse", "mae"])
def test_regression_baselines(tmp_path, metric):
    result = datasets.analyze_dataset(save(tmp_path, sample(task="regression")), design(task="regression", metric=metric), {}, 83)
    assert not blockers(result)
    assert result["baseline"]["status"] == "complete"
    assert result["baseline"]["score"] < result["baseline"]["dummy_score"]


def test_partition_reproducibility_hashes_and_exclusions(tmp_path):
    frame = sample()
    frame["ignored"] = "secret nuisance"
    path = save(tmp_path, frame)
    cfg = design(exclude_columns=["row_id", "ignored"])
    first = datasets.write_partitions(path, cfg, 7, tmp_path / "one")
    second = datasets.write_partitions(path, cfg, 7, tmp_path / "two")
    assert first == second
    for partition in ("train", "test"):
        output = tmp_path / "one" / f"{partition}.csv"
        assert hashlib.sha256(output.read_bytes()).hexdigest() == first[f"{partition}_sha256"]
        assert set(pd.read_csv(output).columns) == {"signal", "category", "target"}
    assert first["train_rows"] + first["test_rows"] == len(frame)


def test_export_preserves_source_text(tmp_path):
    frame = sample()
    frame["code"] = [f"{index:05d}" for index in range(len(frame))]
    path = save(tmp_path, frame)
    datasets.write_partitions(path, design(), 10, tmp_path / "out")
    exported = pd.read_csv(tmp_path / "out" / "train.csv", dtype=str)
    assert exported["code"].str.len().eq(5).all()


def test_baseline_only_receives_outer_training_rows(tmp_path, monkeypatch):
    path = save(tmp_path, sample())
    observed = {}
    real_baseline = datasets._baseline

    def inspect(training, cfg, features, seed):
        observed["ids"] = set(training["row_id"])
        assert cfg["target"] not in features
        assert "row_id" not in features
        return real_baseline(training, cfg, features, seed)

    monkeypatch.setattr(datasets, "_baseline", inspect)
    result = datasets.analyze_dataset(path, design(), {}, 83)
    assert not blockers(result)
    frame = datasets._load_csv(path)
    train, test = datasets._split_indices(frame, design(), 83)
    assert observed["ids"] == set(frame.iloc[train]["row_id"])
    assert not observed["ids"] & set(frame.iloc[test]["row_id"])


def test_groups_stay_separate_in_outer_and_inner_splits(tmp_path):
    frame = sample(600)
    frame["patient"] = np.repeat(np.arange(30), 20)
    path = save(tmp_path, frame)
    cfg = design(split="group", group_column="patient", exclude_columns=["row_id", "patient"])
    result = datasets.analyze_dataset(path, cfg, {}, 83)
    assert not blockers(result)
    assert result["split"]["group_overlap"] == 0
    outer_train, outer_test = datasets._split_indices(frame, cfg, 83)
    assert not set(frame.iloc[outer_train]["patient"]) & set(frame.iloc[outer_test]["patient"])
    training = frame.iloc[outer_train].reset_index(drop=True)
    inner_train, inner_dev = datasets._split_indices(training, cfg, 84)
    assert not set(training.iloc[inner_train]["patient"]) & set(training.iloc[inner_dev]["patient"])
    assert result["baseline"]["status"] == "complete"


def test_time_ties_do_not_cross_either_split(tmp_path):
    frame = sample(600)
    frame["date"] = np.repeat(pd.date_range("2024-01-01", periods=30).astype(str), 20)
    cfg = design(split="time", time_column="date", exclude_columns=["row_id", "date"])
    result = datasets.analyze_dataset(save(tmp_path, frame), cfg, {}, 12)
    assert not blockers(result)
    train, test = datasets._split_indices(frame, cfg, 12)
    assert frame.iloc[train]["date"].max() < frame.iloc[test]["date"].min()
    inner = frame.iloc[train].reset_index(drop=True)
    a, b = datasets._split_indices(inner, cfg, 13)
    assert inner.iloc[a]["date"].max() < inner.iloc[b]["date"].min()
    assert result["baseline"]["status"] == "complete"


@pytest.mark.parametrize("field,value,expected", [("target", "absent", "target"), ("exclude_columns", ["absent"], "unknown_columns"), ("exclude_columns", ["target"], "excluded_target"), ("exclude_columns", "signal", "excluded_columns"), ("metric", "mae", "metric"), ("task", "clustering", "task"), ("split", "manual", "split_strategy"), ("test_fraction", 0.3, "split_ratio"), ("test_fraction", "no", "split_ratio")])
def test_invalid_designs_are_blocked(tmp_path, field, value, expected):
    result = datasets.analyze_dataset(save(tmp_path, sample()), design(**{field: value}), {}, 1)
    assert expected in blockers(result)
    assert result["baseline"]["status"] == "blocked"


@pytest.mark.parametrize("strategy,column,values,expected", [("group", "patient", [None] * 300, "group_missing"), ("group", "patient", ["same"] * 300, "few_groups"), ("time", "date", ["not a date"] * 300, "invalid_time"), ("time", "date", [None] * 300, "time_missing")])
def test_invalid_split_values(tmp_path, strategy, column, values, expected):
    frame = sample()
    frame[column] = values
    result = datasets.analyze_dataset(save(tmp_path, frame), design(split=strategy, **{f"{strategy}_column": column}), {}, 1)
    assert expected in blockers(result)


def test_target_copy_blocked_but_explicit_exclusion_fixes_it(tmp_path):
    frame = sample()
    frame["answer_copy"] = frame["target"] * 7 + 10
    path = save(tmp_path, frame)
    result = datasets.analyze_dataset(path, design(), {}, 83)
    assert any(key.startswith("target_copy") for key in blockers(result))
    with pytest.raises(ValueError, match="blockers"):
        datasets.write_partitions(path, design(), 83, tmp_path / "forbidden")
    assert not (tmp_path / "forbidden").exists()
    fixed = datasets.analyze_dataset(path, design(exclude_columns=["row_id", "answer_copy"]), {}, 83)
    assert not blockers(fixed)


def test_duplicate_predictive_rows_ignore_excluded_identifiers(tmp_path):
    frame = pd.concat([sample(100)] * 4, ignore_index=True)
    frame["row_id"] = np.arange(len(frame))
    result = datasets.analyze_dataset(save(tmp_path, frame), design(), {}, 83)
    assert "duplicate_overlap" in blockers(result)
    assert result["split"]["duplicate_overlap"] > 0


@pytest.mark.parametrize("value,expected", [(np.nan, "missing_target"), (np.inf, "nonfinite_target"), (-np.inf, "nonfinite_target")])
def test_invalid_target_values(tmp_path, value, expected):
    frame = sample()
    frame["target"] = frame["target"].astype(float)
    frame.loc[0, "target"] = value
    result = datasets.analyze_dataset(save(tmp_path, frame), design(), {}, 83)
    assert expected in blockers(result)


def test_constant_and_too_small_target_data(tmp_path):
    frame = sample()
    frame["target"] = 1
    assert "constant_target" in blockers(datasets.analyze_dataset(save(tmp_path, frame), design(), {}, 1))
    assert "split_size" in blockers(datasets.analyze_dataset(save(tmp_path, sample(20)), design(), {}, 1))


def test_auc_requires_binary_zero_one_labels(tmp_path):
    frame = sample()
    frame["target"] = frame["target"].map({0: "no", 1: "yes"})
    assert "auc_labels" in blockers(datasets.analyze_dataset(save(tmp_path, frame), design(metric="roc_auc"), {}, 3))
    frame["target"] = np.arange(len(frame)) % 3
    assert "auc_binary" in blockers(datasets.analyze_dataset(save(tmp_path, frame), design(metric="roc_auc"), {}, 3))
    frame["target"] = (np.arange(len(frame)) % 2).astype(bool)
    assert "auc_labels" in blockers(datasets.analyze_dataset(save(tmp_path, frame), design(metric="roc_auc"), {}, 3))


def test_reserved_evaluation_column(tmp_path):
    frame = sample()
    frame["_autokaggle_id"] = "reserved"
    result = datasets.analyze_dataset(save(tmp_path, frame), design(), {}, 2)
    assert "reserved_column" in blockers(result)


def test_feature_warnings_and_infinite_imputation(tmp_path):
    frame = sample()
    frame["constant"] = 4
    frame.loc[:140, "signal"] = np.nan
    frame.loc[160, "signal"] = np.inf
    result = datasets.analyze_dataset(save(tmp_path, frame), design(exclude_columns=[]), {}, 83)
    assert not blockers(result)
    warnings = {check["id"].split("_")[0] for check in result["checks"] if check["severity"] == "warning"}
    assert {"identifier", "constant", "missing", "nonfinite"}.issubset(warnings)


def test_noise_is_not_declared_impossible(tmp_path):
    frame = sample(600)
    frame["target"] = np.random.default_rng(322).integers(0, 2, len(frame))
    result = datasets.analyze_dataset(save(tmp_path, frame), design(), {}, 83)
    assert not blockers(result)
    assert "A weak baseline does not prove that labels are random or that a task is impossible." in result["limitations"]
    assert "test_score" not in result["baseline"]


def test_baseline_sampling_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets, "MAX_BASELINE_ROWS", 100)
    result = datasets.analyze_dataset(save(tmp_path, sample(1000)), design(), {}, 83)
    assert not blockers(result)
    assert result["baseline"]["fitting_rows"] <= 100
    assert result["baseline"]["validation_rows"] <= 100


def test_missing_only_feature_is_warned_and_imputed(tmp_path):
    frame = sample()
    frame["empty_feature"] = np.nan
    result = datasets.analyze_dataset(save(tmp_path, frame), design(), {}, 83)
    assert not blockers(result)
    assert any(check["title"] == "Missing values: empty_feature" for check in result["checks"])


def test_classes_missing_from_chronological_training_block_export(tmp_path):
    frame = sample()
    frame["time"] = np.arange(len(frame))
    frame["target"] = np.where(frame["time"] < 240, 0, 1)
    cfg = design(split="time", time_column="time", exclude_columns=["row_id", "time"])
    result = datasets.analyze_dataset(save(tmp_path, frame), cfg, {}, 83)
    assert "class_coverage" in blockers(result)


def test_split_cannot_use_target_as_group(tmp_path):
    result = datasets.analyze_dataset(save(tmp_path, sample()), design(split="group", group_column="target"), {}, 83)
    assert "group_target" in blockers(result)


def test_proxy_warning_does_not_claim_proven_leakage(tmp_path):
    frame = sample()
    frame["category_proxy"] = frame["target"].map({0: "low", 1: "high"})
    result = datasets.analyze_dataset(save(tmp_path, frame), design(), {}, 83)
    proxies = [check for check in result["checks"] if check["id"].startswith("target_proxy")]
    assert proxies and proxies[0]["severity"] == "warning"
    assert "valid signal or a label proxy" in proxies[0]["detail"]


@pytest.mark.parametrize("column", ["patient_id", "subject_id", "experiment_id", "site", "lab", "Patient ID"])
def test_random_split_warns_about_repeated_sources_even_if_excluded(tmp_path, column):
    frame = sample(600)
    frame[column] = np.repeat(np.arange(30), 20)
    cfg = design(exclude_columns=["row_id", column])
    path = save(tmp_path, frame)
    result = datasets.analyze_dataset(path, cfg, {}, 83)
    assert not blockers(result)
    warning = next(check for check in result["checks"] if check["id"].startswith("random_group_"))
    assert warning["severity"] == "warning"
    assert "Excluding the column does not separate" in warning["detail"]
    assert "group split" in warning["action"]
    grouped = datasets.analyze_dataset(path, {**cfg, "split": "group", "group_column": column}, {}, 83)
    assert not blockers(grouped)
    assert not any(check["id"].startswith("random_group_") for check in grouped["checks"])
    assert grouped["split"]["group_overlap"] == 0


def test_unique_patient_ids_do_not_warn_about_repeated_groups(tmp_path):
    frame = sample()
    frame["patient_id"] = np.arange(len(frame))
    result = datasets.analyze_dataset(save(tmp_path, frame), design(exclude_columns=["row_id", "patient_id"]), {}, 83)
    assert not blockers(result)
    assert not any(check["id"].startswith("random_group_") for check in result["checks"])
