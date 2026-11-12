"""Portable contract coverage and result evidence checks. Standard library only.

This file is copied into evaluator repositories. Test coverage establishes that
checks ran; it does not establish the scientific correctness of their assertions.
The separate review compares those assertions with the accepted contract.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import unittest

SCHEMA = "bold.lite.quality.v1"
KINDS = {"metric", "input", "output", "provenance", "failure", "resources", "protocol"}


def digest(path):
    """Stream a file or a canonical directory manifest. Never follow links."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Linked artifacts are not supported. Supply the files themselves.")
    if path.is_dir():
        value = hashlib.sha256(b"bold.directory.v1\n")
        for child in sorted(path.rglob("*")):
            if child.is_symlink() or not (child.is_file() or child.is_dir()):
                raise ValueError("Artifacts cannot contain links or special files.")
            if child.is_file():
                entry = [child.relative_to(path).as_posix(), child.stat().st_size, digest(child)]
                value.update((json.dumps(entry, separators=(",", ":"), ensure_ascii=True) + "\n").encode())
        return value.hexdigest()
    if not path.is_file():
        raise ValueError("The artifact is not a regular file or directory.")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def extract_archive(archive, destination, *, max_bytes, max_files=100000):
    """Extract plain files with a declared expanded-size allowance. Reject links."""
    import shutil
    import tarfile
    import zipfile
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    total, seen = 0, set()

    def write(name, size, stream):
        nonlocal total
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not path.parts or name in seen or "\\" in name:
            raise ValueError("An archive has an unsafe or duplicate path.")
        seen.add(name)
        total += size
        if total > max_bytes or len(seen) > max_files or size < 0:
            raise ValueError("The archive exceeds its expanded size or file allowance.")
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as out:
            remaining = size
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("The archive has an incomplete file.")
                out.write(chunk)
                remaining -= len(chunk)
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    if member.is_dir():
                        continue
                    mode = (member.external_attr >> 16) & 0o170000
                    if mode not in (0, 0o100000):
                        raise ValueError("Archive links and special files are forbidden.")
                    with source.open(member) as stream:
                        write(member.filename, member.file_size, stream)
        else:
            with tarfile.open(archive, mode="r|*") as source:
                for member in source:
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("Archive links and special files are forbidden.")
                    with source.extractfile(member) as stream:
                        write(member.name, member.size, stream)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return {"bytes": total, "files": len(seen), "sha256": digest(root)}


def parse_plan(value, contract):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("The contract test plan is missing or has an unknown schema.")
    requirements = value.get("requirements")
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 300:
        raise ValueError("The plan needs 1 to 300 atomic requirements.")
    seen, fields = set(), set()
    for item in requirements:
        if not isinstance(item, dict):
            raise ValueError("Each requirement must be an object.")
        identifier, field, quote = item.get("id"), item.get("field"), item.get("quote")
        source = contract.get(field) if isinstance(field, str) else None
        source = source if isinstance(source, str) else json.dumps(source, sort_keys=True)
        if not isinstance(identifier, str) or not re.fullmatch(r"R[0-9]{3}", identifier) or identifier in seen:
            raise ValueError("Requirements need distinct IDs such as R001.")
        if field not in contract or not isinstance(quote, str) or not quote.strip() or quote not in source:
            raise ValueError(f"{identifier}: quote the exact accepted contract field.")
        if item.get("kind") not in KINDS or not isinstance(item.get("behavior"), str) or len(item["behavior"].strip()) < 10:
            raise ValueError(f"{identifier}: define a concrete behavior and its category.")
        seen.add(identifier)
        fields.add(field)
    # Titles do not affect execution. Every other supplied field needs review.
    missing = {k for k, v in contract.items() if v not in (None, "", [], {}) and k != "title"} - fields
    if missing:
        raise ValueError("The plan omits contract fields: " + ", ".join(sorted(missing)))
    result = value.get("result_requirements")
    if not isinstance(result, dict) or set(result) != {"metrics", "outputs", "reference_required"}:
        raise ValueError("Define result metrics, output names, and reference_required.")
    for name in ("metrics", "outputs"):
        entries = result[name]
        if (not isinstance(entries, list) or len(entries) > 150 or len(set(map(str, entries))) != len(entries)
                or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", v) for v in entries)):
            raise ValueError("Result requirements need distinct plain metric and output names.")
    if type(result["reference_required"]) is not bool:
        raise ValueError("reference_required must be a boolean.")
    return value


def parse_coverage(value, plan):
    """A declared mapping alone is not coverage. run_suite checks execution."""
    if not isinstance(value, dict) or set(value) != {r["id"] for r in plan["requirements"]}:
        raise ValueError("coverage.json must map every requirement, with no unknown IDs.")
    for identifier, tests in value.items():
        if (not isinstance(tests, list) or not tests or len(tests) > 100
                or any(not isinstance(t, str) or not re.fullmatch(r"test_[A-Za-z0-9_.]+", t) for t in tests)):
            raise ValueError(f"{identifier}: name the unittest IDs that check this requirement.")
    return value


class EvidenceResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.outcomes = {}

    def startTest(self, test):
        super().startTest(test)
        self.outcomes[test.id()] = False

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[test.id()] = True

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error:
            self.outcomes[test.id()] = False


def run_suite(root, plan):
    root = Path(root)
    mapping = parse_coverage(json.loads((root / "coverage.json").read_text()), plan)
    suite = unittest.TestLoader().discover(str(root / "tests"), pattern="test_*.py")
    result = EvidenceResult()
    suite.run(result)
    covered = {key: bool(tests) and all(result.outcomes.get(t) is True for t in tests) for key, tests in mapping.items()}
    passed = result.wasSuccessful() and not result.skipped and not result.expectedFailures and result.testsRun > 0 and all(covered.values())
    errors = [str(test.id()) + ": " + trace[-1500:] for test, trace in result.errors + result.failures]
    return {"passed": passed, "tests_run": result.testsRun, "requirements": covered, "tests": result.outcomes,
            "skipped": [t.id() for t, _ in result.skipped], "errors": errors[:50]}


def result_evidence(record, manifest, plan):
    """Verify required metrics and durable output files in a completed seed."""
    if record.get("status") != "completed":
        return record
    requirements = plan["result_requirements"]
    metrics = record.get("metrics", {})
    for name in requirements["metrics"]:
        value = metrics.get(name) if isinstance(metrics, dict) else None
        # Curves can be saved as required outputs. Summary metrics must be finite.
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Required metric '{name}' is missing or not finite.")
    if requirements["reference_required"]:
        reference = record.get("reference")
        if (not isinstance(reference, dict) or reference.get("mode") != manifest.get("evaluation_mode")
                or not isinstance(reference.get("identity"), str) or not reference["identity"].strip()
                or not re.fullmatch(r"[a-f0-9]{64}", str(reference.get("sha256", "")))):
            raise ValueError("Record the selected reference identity, digest, and evaluation mode.")
        expected = manifest.get("reference_sha256")
        if expected and reference["sha256"] != expected:
            raise ValueError("The result used a different reference dataset.")
    root = Path(manifest["output_directory"]).resolve()
    outputs = record.get("outputs", {})
    checked = {}
    for name in requirements["outputs"]:
        relative = outputs.get(name) if isinstance(outputs, dict) else None
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"Required output '{name}' needs a relative file path.")
        file = root / relative
        if not file.resolve().is_relative_to(root) or not file.is_file() or file.is_symlink():
            raise ValueError(f"Required output '{name}' was not saved in the result directory.")
        checked[name] = {"path": relative, "bytes": file.stat().st_size, "sha256": digest(file)}
    record["output_files"] = checked
    record["evaluation_mode"] = manifest["evaluation_mode"]
    return record


def validate_metadata(record):
    """Check reported metadata syntax. This does not fetch or verify its files."""
    fields = {"seed", "status", "score", "steps", "elapsed_seconds", "end_reason", "metrics", "outputs",
              "reference", "output_files", "evaluation_mode", "output_directory"}
    if set(record) - fields or len(json.dumps(record, allow_nan=False)) > 64000:
        raise ValueError("Use bounded result metadata. Store large outputs in the artifact reference.")
    def named_map(value, label):
        if (not isinstance(value, dict) or len(value) > 150 or
                any(not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", k) for k in value)):
            raise ValueError(label + " needs a bounded map of named values.")
        return value
    def relative(value):
        return (isinstance(value, str) and 0 < len(value) <= 1000 and not Path(value).is_absolute()
                and ".." not in Path(value).parts and "\\" not in value)
    for name, value in named_map(record.get("metrics", {}), "Metrics").items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Reported metrics must be finite numbers.")
    outputs = named_map(record.get("outputs", {}), "Outputs")
    if any(not relative(value) for value in outputs.values()):
        raise ValueError("Output paths must be relative paths inside the result directory.")
    for name, value in named_map(record.get("output_files", {}), "Output evidence").items():
        if (not isinstance(value, dict) or set(value) != {"path", "bytes", "sha256"}
                or value["path"] != outputs.get(name) or not relative(value["path"])
                or type(value["bytes"]) is not int or value["bytes"] < 0
                or not re.fullmatch(r"[a-f0-9]{64}", str(value["sha256"]))):
            raise ValueError("Each output needs its relative path, byte count, and SHA-256.")
    if "evaluation_mode" in record and record["evaluation_mode"] not in {"synthetic", "research"}:
        raise ValueError("Declare synthetic or research evaluation mode.")
    if "output_directory" in record and not relative(record["output_directory"]):
        raise ValueError("Use a relative per-seed output directory.")
    if "reference" in record:
        ref = record["reference"]
        if (not isinstance(ref, dict) or set(ref) != {"identity", "sha256", "mode"}
                or not isinstance(ref["identity"], str) or not 1 <= len(ref["identity"].strip()) <= 1000
                or not re.fullmatch(r"[a-f0-9]{64}", str(ref["sha256"]))
                or ref["mode"] not in {"synthetic", "research"}
                or ("evaluation_mode" in record and ref["mode"] != record["evaluation_mode"])):
            raise ValueError("Reference evidence needs an identity, SHA-256, and matching mode.")
    return record


if __name__ == "__main__":
    import sys
    root = Path.cwd()
    plan = parse_plan(json.loads((root / "quality.json").read_text()), json.loads((root / "contract.json").read_text())["contract"])
    result = run_suite(root, plan)
    Path(sys.argv[1]).write_text(json.dumps(result, allow_nan=False))
    raise SystemExit(0 if result["passed"] else 1)
