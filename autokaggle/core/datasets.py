"""CSV audits and repeatable dataset partitions.

Only the organizer calls this module. The baseline fits and scores an inner
partition of the training data; it never receives the final held-out rows.
"""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, balanced_accuracy_score, mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

MAX_UPLOAD_MB = 200
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_ROWS = 1_000_000
MAX_COLUMNS = 200
MAX_CELLS = 10_000_000
MAX_BASELINE_ROWS = 5_000
MIN_TRAIN_ROWS = 20
MIN_TEST_ROWS = 5
CLASSIFICATION_METRICS = {"accuracy", "balanced_accuracy", "roc_auc"}
REGRESSION_METRICS = {"rmse", "mae"}


def upload_limit_message() -> str:
    return (
        f"Upload a CSV file of up to {MAX_UPLOAD_MB} MB. For a larger file, paste a Google Drive link "
        'in the interview. Set sharing to "Anyone with the link" and the role to "Viewer".'
    )


def _load_csv(path: Path) -> pd.DataFrame:
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("The CSV file could not be read.") from exc
    if size > MAX_BYTES:
        raise ValueError(upload_limit_message())
    if size == 0:
        raise ValueError("The CSV file is empty.")
    csv.field_size_limit(1024 * 1024)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            headers = next(reader, None)
            if not headers:
                raise ValueError("The CSV needs a header row.")
            headers = [name.strip() for name in headers]
            if any("\x00" in name for name in headers):
                raise ValueError("CSV column names cannot contain null bytes.")
            if not all(headers):
                raise ValueError("Each CSV column must have a name.")
            if len(set(headers)) != len(headers):
                raise ValueError("CSV column names must be unique, including after spaces are removed from their ends.")
            if len(headers) > MAX_COLUMNS:
                raise ValueError(f"The prototype accepts at most {MAX_COLUMNS} columns.")
            rows = 0
            for row in reader:
                if not row:
                    continue
                if len(row) != len(headers):
                    raise ValueError(f"CSV row {reader.line_num} has {len(row)} fields; the header has {len(headers)}.")
                if any("\x00" in cell for cell in row):
                    raise ValueError("CSV cells cannot contain null bytes.")
                rows += 1
                if rows > MAX_ROWS or rows * len(headers) > MAX_CELLS:
                    raise ValueError(f"The prototype accepts at most {MAX_ROWS:,} rows and {MAX_CELLS:,} cells.")
            if rows == 0:
                raise ValueError("The CSV has a header but no data rows.")
        frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        frame.columns = headers
        if len(frame) != rows:
            raise ValueError("The CSV contains rows that cannot be parsed consistently.")
    except (UnicodeError, csv.Error, pd.errors.ParserError, pd.errors.EmptyDataError, OSError) as exc:
        raise ValueError("The file must be a valid UTF-8 CSV with a consistent number of fields in each row.") from exc
    if any("\x00" in name for name in headers):
        raise ValueError("CSV column names cannot contain null bytes.")
    return frame


def profile_csv(path: Path) -> dict:
    """Validate and profile a bounded UTF-8 CSV without exposing sample values."""
    frame = _load_csv(path)
    return {
        "rows": len(frame),
        "columns": [
            {"name": str(name), "dtype": str(frame[name].dtype),
             "missing": int(frame[name].isna().sum()), "unique": int(frame[name].nunique(dropna=True))}
            for name in frame.columns
        ],
        "size_bytes": Path(path).stat().st_size,
    }


def _check(checks: list, key: str, severity: str, title: str, detail: str, action: str = "") -> None:
    checks.append({"id": key, "severity": severity, "title": title, "detail": detail, "action": action})


def _has_blockers(checks: list) -> bool:
    return any(item["severity"] == "blocker" for item in checks)


def _time_values(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce")
        return numeric.where(np.isfinite(numeric))
    return pd.to_datetime(series, errors="coerce", utc=True, format="mixed")


def _validate_design(frame: pd.DataFrame, design: dict, checks: list) -> list[str]:
    target = design.get("target", "")
    task = design.get("task", "classification")
    metric = design.get("metric", "accuracy")
    strategy = design.get("split", "random")
    excluded = design.get("exclude_columns", [])
    if "_autokaggle_id" in frame.columns:
        _check(checks, "reserved_column", "blocker", "Reserved column name", "The name _autokaggle_id is reserved for evaluation row identifiers.", "Rename this source column.")
    if not isinstance(excluded, list) or any(not isinstance(name, str) for name in excluded):
        _check(checks, "excluded_columns", "blocker", "Invalid excluded columns", "Excluded columns must be a list of column names.", "Select columns from the uploaded CSV.")
        excluded = []
    unknown = sorted(set(excluded) - set(frame.columns))
    if unknown:
        _check(checks, "unknown_columns", "blocker", "Unknown excluded columns", "These columns do not exist: " + ", ".join(unknown), "Select columns from the uploaded CSV.")
    if target not in frame.columns:
        _check(checks, "target", "blocker", "Select a target", "The target column is missing or does not exist.", "Select the label or measurement that the model must predict.")
    if target in excluded:
        _check(checks, "excluded_target", "blocker", "The target cannot be excluded", "Training data must retain the target column.", "Remove the target from excluded columns.")
    if task not in {"classification", "regression"}:
        _check(checks, "task", "blocker", "Unsupported task", "Choose classification or regression.")
    if metric not in (CLASSIFICATION_METRICS if task == "classification" else REGRESSION_METRICS):
        _check(checks, "metric", "blocker", "Metric does not match the task", f"The metric {metric!r} cannot evaluate this {task} task.", "Choose a metric for the selected task.")
    if strategy not in {"random", "group", "time"}:
        _check(checks, "split_strategy", "blocker", "Unsupported split", "Choose random, group, or time.")
    try:
        ratio_valid = not isinstance(design.get("test_fraction", 0.2), bool) and math.isclose(float(design.get("test_fraction", 0.2)), 0.2, abs_tol=1e-12)
    except (ValueError, TypeError):
        ratio_valid = False
    if not ratio_valid:
        _check(checks, "split_ratio", "blocker", "Use the 80/20 split", "This prototype reserves 20% of rows, or approximately 20% when groups or equal times must stay together.")
    for kind, column_key in (("group", "group_column"), ("time", "time_column")):
        if strategy != kind:
            continue
        column = design.get(column_key, "")
        if not column or column not in frame.columns:
            _check(checks, f"{kind}_column", "blocker", f"Select a {kind} column", f"The {kind} split needs an existing column.")
        elif column == target:
            _check(checks, f"{kind}_target", "blocker", "Do not split by the target", "A split column must describe the source or order of observations.", f"Choose another {kind} column.")
        elif frame[column].isna().any():
            _check(checks, f"{kind}_missing", "blocker", f"Missing {kind} values", "Every row needs a split value.", "Supply the missing values or repair the source data.")
        elif kind == "group" and frame[column].nunique() < 3:
            _check(checks, "few_groups", "blocker", "Too few independent groups", "At least three groups are needed for training, development, and the final test.", "Supply more independent groups.")
        elif kind == "time" and _time_values(frame[column]).isna().any():
            _check(checks, "invalid_time", "blocker", "Invalid time values", "Time values must be valid dates or finite numeric times.", "Use one consistent time format.")
    features = [name for name in frame.columns if name != target and name not in excluded]
    if not features:
        _check(checks, "no_features", "blocker", "No predictive features", "The design must retain at least one feature in addition to the target.")
    if target not in frame.columns:
        return features
    y = frame[target]
    if y.isna().any():
        _check(checks, "missing_target", "blocker", "Missing target values", f"{int(y.isna().sum())} rows have no target.", "Supply verified labels before splitting the data.")
    numeric_y = pd.to_numeric(y, errors="coerce")
    nonfinite = y.astype(str).str.strip().str.lower().isin({"inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"})
    nonfinite |= numeric_y.notna() & ~np.isfinite(numeric_y)
    if nonfinite.any():
        _check(checks, "nonfinite_target", "blocker", "Non-finite target values", "Targets cannot contain positive or negative infinity.")
    if task == "regression" and (numeric_y.isna().any() or (~np.isfinite(numeric_y)).any()):
        _check(checks, "numeric_target", "blocker", "Regression needs finite numbers", "Every regression target must be a finite numeric value.")
    if y.nunique() < 2:
        _check(checks, "constant_target", "blocker", "The target is constant", "The target needs variation for a useful challenge.", "Check the target and collect more varied observations.")
    if task == "classification":
        classes = y.nunique()
        if classes > 100:
            _check(checks, "many_classes", "blocker", "Too many classes for this prototype", "Classification is limited to 100 target classes.", "Check whether this is a regression task.")
        elif classes > 20:
            _check(checks, "many_classes", "warning", "Many target classes", f"The target has {classes} classes.", "Check that these are class labels, rather than continuous measurements.")
        if metric == "roc_auc" and classes != 2:
            _check(checks, "auc_binary", "blocker", "ROC AUC needs two classes", "This prototype supports binary ROC AUC only.")
        elif metric == "roc_auc" and (pd.api.types.is_bool_dtype(y) or numeric_y.isna().any() or set(numeric_y) != {0, 1}):
            _check(checks, "auc_labels", "blocker", "ROC AUC labels must be 0 and 1", "The reference scorer expects a probability for class 1.", "Recode binary labels as numeric 0 and 1.")
        if y.value_counts().min() < 2:
            _check(checks, "rare_class", "blocker", "A class has too few examples", "Each class needs at least two rows before a useful split can be considered.", "Collect more examples or review the class definition.")
    return features


def _split_indices(frame: pd.DataFrame, design: dict, seed: int) -> tuple[np.ndarray, np.ndarray]:
    strategy = design.get("split", "random")
    indices = np.arange(len(frame))
    seed = int(seed) % (2 ** 32)
    if strategy == "group":
        return next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed).split(indices, groups=frame[design["group_column"]]))
    if strategy == "time":
        times = _time_values(frame[design["time_column"]])
        ordered = times.sort_values(kind="stable")
        cutoff = ordered.iloc[min(int(len(frame) * 0.8), len(frame) - 1)]
        return np.flatnonzero((times < cutoff).to_numpy()), np.flatnonzero((times >= cutoff).to_numpy())
    stratify = frame[design["target"]] if design.get("task", "classification") == "classification" else None
    train, test = train_test_split(indices, test_size=0.2, random_state=seed, stratify=stratify)
    return np.sort(train), np.sort(test)


def _feature_checks(frame: pd.DataFrame, features: list[str], target: str, task: str, checks: list) -> None:
    y = frame[target]
    yn = pd.to_numeric(y, errors="coerce")
    yn_finite = yn.notna() & np.isfinite(yn)
    for position, name in enumerate(features):
        column = frame[name]
        unique = int(column.nunique())
        missing = float(column.isna().mean())
        if missing >= 0.3:
            _check(checks, f"missing_{position}", "warning", f"Missing values: {name}", f"{missing:.0%} of this feature is missing.", "Explain missing values and check whether they reveal data collection or labels.")
        if unique <= 1:
            _check(checks, f"constant_{position}", "warning", f"Constant feature: {name}", "This column has at most one observed value and adds no predictive variation.", "Consider excluding it.")
            continue
        complete = column.notna() & y.notna()
        string_copy = complete.all() and column.astype(str).equals(y.astype(str))
        xn = pd.to_numeric(column, errors="coerce")
        paired = yn_finite & xn.notna() & np.isfinite(xn)
        affine_copy = False
        correlation = None
        if paired.sum() >= max(20, math.ceil(len(frame) * 0.8)) and xn[paired].nunique() > 1 and yn[paired].nunique() > 1:
            correlation = float(xn[paired].corr(yn[paired]))
            affine_copy = math.isfinite(correlation) and abs(correlation) >= 1 - 1e-12
        if string_copy or affine_copy:
            _check(checks, f"target_copy_{position}", "blocker", f"Possible target copy: {name}", "This feature equals the target or has an exact linear relation to it. This can expose the answer.", "Exclude it, or redesign the task after checking how the feature was measured.")
        elif correlation is not None and math.isfinite(correlation) and abs(correlation) >= 0.995:
            _check(checks, f"target_proxy_{position}", "warning", f"Possible target proxy: {name}", "This feature has a near-perfect linear relation to the target. This is a review signal, not proof of leakage.", "Verify that the feature exists before the outcome is known.")
        elif task == "classification" and 1 < unique <= min(50, len(frame) // 5) and complete.all():
            mapping = pd.DataFrame({"x": column.astype(str), "y": y.astype(str)}).groupby("x")["y"].nunique()
            if mapping.max() == 1:
                _check(checks, f"target_proxy_{position}", "warning", f"Possible class proxy: {name}", "Each value of this feature maps to one class in this sample. This can be valid signal or a label proxy.", "Verify its origin and availability at prediction time.")
        numeric = pd.api.types.is_numeric_dtype(column)
        if numeric and (~np.isfinite(column.dropna())).any():
            _check(checks, f"nonfinite_feature_{position}", "warning", f"Non-finite feature: {name}", "The baseline treats infinite feature values as missing. Exported data retain the source values.", "Repair these values or define a valid missing-value rule.")
        if unique >= len(frame) * 0.95 and (not numeric or column.is_monotonic_increasing or column.is_monotonic_decreasing or name.lower().endswith(("id", "index", "uuid"))):
            _check(checks, f"identifier_{position}", "warning", f"Possible row identifier: {name}", "Almost every row has a distinct value. Identifiers can link rows to public answers or collection order.", "Exclude identifiers unless their use has a scientific reason.")


def _independence_checks(frame: pd.DataFrame, design: dict, checks: list) -> None:
    """Review source columns even when they are excluded from prediction."""
    if design.get("split", "random") != "random":
        return
    source_name = re.compile(r"^(patient|subject|participant|person|individual|animal|donor|site|hospital|center|centre|lab|laboratory|batch|experiment|session|device|household|family|source)(?:_?(?:id|code|name))?$", re.IGNORECASE)
    for position, name in enumerate(frame.columns):
        if name == design.get("target"):
            continue
        normalized = re.sub(r"[\s-]+", "_", name.strip())
        if not source_name.fullmatch(normalized) and name != design.get("group_column"):
            continue
        values = frame[name].dropna()
        groups = int(values.nunique())
        if groups == 0 or len(values) <= groups:
            continue
        detail = f"This column has {groups} source values across {len(values)} rows. A random row split can put related observations in both training and test data. Excluding the column does not separate those observations."
        action = "Use a group split if these rows share a source, or document why the observations are independent."
        if groups == 1:
            action += " More independent groups are needed to test transfer to new sources."
        _check(checks, f"random_group_{position}", "warning", f"Repeated source groups: {name}", detail, action)


def _partition_checks(frame: pd.DataFrame, design: dict, features: list[str], train: np.ndarray, test: np.ndarray, checks: list) -> dict:
    strategy = design.get("split", "random")
    result = {"train_rows": len(train), "test_rows": len(test), "strategy": strategy, "group_overlap": 0, "duplicate_overlap": 0}
    if len(train) < MIN_TRAIN_ROWS or len(test) < MIN_TEST_ROWS:
        _check(checks, "split_size", "blocker", "Too few rows after the split", f"The split has {len(train)} training rows and {len(test)} test rows. At least 20 and 5 are required.", "Supply more independent observations or review the split.")
        return result
    if strategy == "group":
        group = frame[design["group_column"]]
        overlap = set(group.iloc[train]) & set(group.iloc[test])
        result["group_overlap"] = len(overlap)
        _check(checks, "group_isolation", "pass" if not overlap else "blocker", "Group isolation", "No group appears in both partitions." if not overlap else "Some groups occur in both partitions.")
    elif strategy == "time":
        times = _time_values(frame[design["time_column"]])
        separated = times.iloc[train].max() < times.iloc[test].min()
        _check(checks, "time_order", "pass" if separated else "blocker", "Time order", "All training observations occur before the test observations; equal times stay together." if separated else "Time ranges overlap.")
    actual = len(test) / len(frame)
    if abs(actual - 0.2) > 0.05:
        _check(checks, "split_proportion", "warning", "Split ratio changed to preserve independence", f"The test set contains {actual:.1%} of rows because groups or equal times stay together.", "Check that the number of independent test observations is sufficient.")
    fingerprints = pd.util.hash_pandas_object(frame[features], index=False)
    train_hashes = set(fingerprints.iloc[train])
    duplicate_count = int(fingerprints.iloc[test].isin(train_hashes).sum())
    result["duplicate_overlap"] = duplicate_count
    if duplicate_count:
        _check(checks, "duplicate_overlap", "blocker", "Duplicate features cross the split", f"{duplicate_count} test rows have the same predictive features as a training row, after excluded columns are removed.", "Review duplicates, remove repeated observations, or group related rows before splitting.")
    else:
        _check(checks, "duplicate_overlap", "pass", "No exact feature duplicates cross the split", "The retained features have no exact duplicate rows across these partitions. Near duplicates still need review.")
    if design.get("task", "classification") == "classification":
        target = design["target"]
        train_classes, test_classes = set(frame[target].iloc[train]), set(frame[target].iloc[test])
        if not test_classes.issubset(train_classes) or len(train_classes) < 2:
            _check(checks, "class_coverage", "blocker", "Training classes do not cover the test task", "Training needs at least two classes and must include each class in the test set.", "Collect more examples or review the split and task.")
        elif len(test_classes) < 2:
            _check(checks, "class_coverage", "blocker" if design.get("metric") == "roc_auc" else "warning", "The test set has only one class", "The test set cannot measure performance across classes.", "Supply more independent observations or review the split.")
        else:
            _check(checks, "class_coverage", "pass", "Classes represented", "Training and test data each contain at least two classes; all test classes occur in training.")
    _check(checks, "split_size", "pass", "Partition sizes meet the prototype minimum", f"{len(train)} training rows and {len(test)} hidden test rows. This minimum is not a statistical power calculation.")
    return result


def _score(metric: str, model: Any, x: pd.DataFrame, y: pd.Series) -> float:
    prediction = model.predict(x)
    if metric == "accuracy":
        return float(accuracy_score(y, prediction))
    if metric == "balanced_accuracy":
        return float(balanced_accuracy_score(y, prediction))
    if metric == "roc_auc":
        return float(roc_auc_score(y == model.classes_[1], model.predict_proba(x)[:, 1]))
    if metric == "mae":
        return float(mean_absolute_error(y, prediction))
    return float(math.sqrt(mean_squared_error(y, prediction)))


def _baseline(training: pd.DataFrame, design: dict, features: list[str], seed: int) -> dict:
    """Do not pass final-test data to this function."""
    metric = design.get("metric", "accuracy")
    result = {"status": "unavailable", "metric": metric, "score": None, "dummy_score": None, "validation_rows": 0, "detail": ""}
    # Bound model work after splitting, so the development split still respects
    # complete groups and chronological boundaries in the full training set.
    try:
        inner_train, validation = _split_indices(training, design, seed + 1)
        if len(inner_train) < 10 or len(validation) < 5:
            raise ValueError("The training set is too small for an independent development split.")
        development = training.iloc[validation]
        fitting = training.iloc[inner_train]
        train_fingerprints = set(pd.util.hash_pandas_object(fitting[features], index=False))
        dev_fingerprints = pd.util.hash_pandas_object(development[features], index=False)
        if dev_fingerprints.isin(train_fingerprints).any():
            raise ValueError("Exact feature duplicates cross the inner development split. Review duplicates or group related observations.")
        sampled = len(fitting) > MAX_BASELINE_ROWS or len(development) > MAX_BASELINE_ROWS
        if len(fitting) > MAX_BASELINE_ROWS:
            fitting = fitting.sample(MAX_BASELINE_ROWS, random_state=int(seed) % (2 ** 32))
        if len(development) > MAX_BASELINE_ROWS:
            development = development.sample(MAX_BASELINE_ROWS, random_state=(int(seed) + 1) % (2 ** 32))
        x_train = fitting[features].copy()
        x_dev = development[features].copy()
        numeric = [name for name in features if pd.api.types.is_numeric_dtype(x_train[name])]
        categorical = [name for name in features if name not in numeric]
        for frame in (x_train, x_dev):
            frame[numeric] = frame[numeric].replace([np.inf, -np.inf], np.nan)
            for name in categorical:
                frame[name] = frame[name].astype(object).where(frame[name].notna(), np.nan)
        processors = []
        if numeric:
            processors.append(("numeric", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True), numeric))
        if categorical:
            processors.append(("categories", Pipeline([("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)), ("encode", OneHotEncoder(handle_unknown="ignore", max_categories=32, sparse_output=True))]), categorical))
        classification = design.get("task", "classification") == "classification"
        y_train, y_dev = fitting[design["target"]], development[design["target"]]
        if classification:
            # String labels avoid scikit-learn treating numeric class names as
            # continuous outcomes, without using held-out target values.
            y_train, y_dev = y_train.astype(str), y_dev.astype(str)
            if y_train.nunique() < 2 or not set(y_dev).issubset(set(y_train)):
                raise ValueError("The development split has classes that cannot be learned from its training rows.")
            if metric == "roc_auc" and y_dev.nunique() != 2:
                raise ValueError("The development split needs both classes for ROC AUC.")
        estimator_cls = DecisionTreeClassifier if classification else DecisionTreeRegressor
        estimator = estimator_cls(max_depth=5, min_samples_leaf=max(2, len(fitting) // 100), random_state=int(seed) % (2 ** 32))
        model = Pipeline([("features", ColumnTransformer(processors)), ("model", estimator)])
        model.fit(x_train, y_train)
        dummy = DummyClassifier(strategy="most_frequent") if classification else DummyRegressor(strategy="mean")
        dummy.fit(x_train, y_train)
        score, dummy_score = _score(metric, model, x_dev, y_dev), _score(metric, dummy, x_dev, y_dev)
        if not math.isfinite(score) or not math.isfinite(dummy_score):
            raise ValueError("The metric could not produce a finite development score.")
        detail = f"A depth-5 decision tree and a simple constant baseline used a {design.get('split', 'random')} development split within the training partition. The final test set was not fitted or scored."
        if sampled:
            detail += f" Model fitting and development scoring each used at most {MAX_BASELINE_ROWS:,} sampled rows to bound prototype compute."
        result.update(status="complete", score=score, dummy_score=dummy_score, validation_rows=len(development), fitting_rows=len(fitting), detail=detail)
    except (ValueError, TypeError, OverflowError) as exc:
        result["detail"] = "The training-only baseline could not run: " + str(exc)
    return result


def analyze_dataset(path: Path, design: dict, answers: dict, seed: int) -> dict:
    """Return findings and an inner-development baseline, never a test score."""
    frame = _load_csv(path)
    checks: list[dict] = []
    features = _validate_design(frame, design, checks)
    result: dict = {
        "checks": checks, "split": None,
        "baseline": {"status": "blocked", "metric": design.get("metric", "accuracy"), "score": None, "dummy_score": None, "validation_rows": 0, "detail": "Resolve dataset design blockers before running a baseline."},
        "limitations": [
            "Automated checks cannot prove that data are free of leakage or that a task is scientifically valid.",
            "Exact duplicate and simple proxy checks do not detect all near duplicates, public answer lookup, or information collected after the outcome.",
            "The baseline score uses development data inside training. It is not a final test score or evidence of statistical significance.",
            "A weak baseline does not prove that labels are random or that a task is impossible.",
        ],
    }
    if not _has_blockers(checks):
        _independence_checks(frame, design, checks)
        _feature_checks(frame, features, design["target"], design.get("task", "classification"), checks)
        try:
            train, test = _split_indices(frame, design, seed)
            result["split"] = _partition_checks(frame, design, features, train, test, checks)
            if not _has_blockers(checks):
                result["baseline"] = _baseline(frame.iloc[train].reset_index(drop=True), design, features, seed)
                baseline = result["baseline"]
                if baseline["status"] != "complete":
                    _check(checks, "baseline", "blocker", "Development trial needs repair", baseline["detail"], "Supply more independent training examples or review the split.")
                else:
                    _check(checks, "baseline", "pass", "Training-only baseline completed", baseline["detail"])
                    higher_better = design.get("task", "classification") == "classification"
                    better = baseline["score"] > baseline["dummy_score"] if higher_better else baseline["score"] < baseline["dummy_score"]
                    if not better:
                        _check(checks, "baseline_signal", "warning", "Baseline did not beat the simple reference", "This bounded development trial did not improve on the constant baseline. This does not prove there is no learnable signal.", "Review labels, features, sample size, and domain baselines.")
        except (ValueError, TypeError) as exc:
            _check(checks, "split_failed", "blocker", "The split could not be made", str(exc), "Check class counts and the selected group or time column.")
    result["summary"] = {"blockers": sum(c["severity"] == "blocker" for c in checks), "warnings": sum(c["severity"] == "warning" for c in checks), "passed": sum(c["severity"] == "pass" for c in checks)}
    return result


def write_partitions(path: Path, design: dict, seed: int, output_dir: Path) -> dict:
    """Write the exact audited split. Refuse invalid or leaking designs."""
    # Re-run inexpensive audits, including the bounded baseline, so callers
    # cannot export a different or invalid design after an earlier analysis.
    analysis = analyze_dataset(path, design, {}, seed)
    if analysis["summary"]["blockers"]:
        raise ValueError("Resolve dataset blockers before exporting: " + "; ".join(c["title"] for c in analysis["checks"] if c["severity"] == "blocker"))
    frame = _load_csv(path)
    train, test = _split_indices(frame, design, seed)
    # Preserve source text such as leading zeroes and decimal precision in
    # exports. Numeric inference is used only for checks and baseline fitting.
    raw_frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    raw_frame.columns = frame.columns
    excluded = set(design.get("exclude_columns", []))
    columns = [name for name in frame.columns if name not in excluded]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {"train_rows": len(train), "test_rows": len(test), "columns": columns}
    for name, indices in (("train", train), ("test", test)):
        output = output_dir / f"{name}.csv"
        raw_frame.iloc[indices][columns].to_csv(output, index=False, lineterminator="\n")
        result[f"{name}_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    return result
