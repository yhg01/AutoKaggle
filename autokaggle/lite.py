"""Internal ML onboarding and researcher-run evaluation contracts.

Lite has separate state and routes. It never starts paid compute or runs uploads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import secrets
import subprocess
import sys
import zipfile
from typing import Any
from urllib.parse import quote

from fastapi import File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from . import onboarding_setup, sources, workspace
from .lite_runner import summarize, validate_record
from .store import now

HERE = Path(__file__).parent
FORMAT = "bold.autokaggle.lite.contract.v1"
GROUPS = (
    ("objective", "Research objective", ("bold_project_url", "objective", "task_kind")),
    ("sources", "Data or environment", ("source_url", "source_revision", "inputs", "allowed_data", "answer_exposure")),
    ("submission", "Artifact and interface", ("artifact_type", "outputs", "adapter_entrypoint")),
    ("evaluation", "Evaluation protocol", ("metric", "success_definition", "evaluation_protocol", "evaluation_count", "failure_policy", "timeout_seconds", "total_timeout_seconds")),
    ("resources", "Training and resources", ("training_policy", "compute_budget")),
    ("provenance", "Reproduction record", ("dependencies",)),
)
STRINGS = {"bold_project_url", "title", "objective", "source_url", "source_revision", "inputs", "outputs", "success_definition",
           "evaluation_protocol", "training_policy", "compute_budget", "dependencies", "adapter_entrypoint",
           "allowed_data", "baseline", "env_id", "success_key", "metric_name", "metric_definition",
           "constraints", "temporal_policy", "generation_policy"}
ENUMS = {"task_kind": {"environment", "batch", "optimization", "forecasting", "generation", "custom"}, "artifact_type": {"predictions", "checkpoint", "policy", "candidate", "code", "samples"},
         "metric": {"success_rate", "mean_score", "accuracy", "rmse", "mae", "custom"},
         "metric_direction": {"maximize", "minimize"},
         "failure_policy": {"zero", "fail_run"}, "answer_exposure": {"visible", "private", "environment_generated"},
         "seed_method": {"reset", "core_disp"}, "horizon_policy": {"require_termination", "fixed_horizon"}}
INTS = {"evaluation_count": (1, 10000), "timeout_seconds": (1, 21600), "total_timeout_seconds": (1, 604800), "max_steps": (1, 100000000),
        "seed_start": (0, 2**32-1), "seed_end": (0, 2**32-1)}
FIELDS = STRINGS | set(ENUMS) | set(INTS) | {"environment_imports", "environment_kwargs"}
CONTRACT_HELP = {
    "bold_project_url": "Required BOLD OS project link: https://bold-lab-ai.github.io/bold-os/project.html#id=<project-id>. Ask the researcher which existing project owns this experiment. Never infer project membership from a paper or repository.",
    "task_kind": "environment for interactive episodes; batch for fixed data; optimization for feasible candidates; forecasting for time-dependent evaluation; generation for generated samples; custom for other declared protocols",
    "metric_name": "Name of a custom fitness measure, such as Sharpe ratio, F1, or energy",
    "metric_definition": "Exact formula or pinned scorer, units, sample aggregation, invalid-case behavior, and numeric tolerance",
    "metric_direction": "Whether larger or smaller custom fitness values are better",
    "constraints": "Optimization feasibility rules, constraint tolerances, and treatment of infeasible candidates",
    "temporal_policy": "Information available at each time, cutoff, leakage prevention, evaluation windows, and costs/execution/risk rules when applicable",
    "generation_policy": "Sample count, reference data, sampling settings, scoring protocol, and variability",
    "metric": "Built-in metric or custom. Custom requires metric_name, metric_definition and metric_direction. Per-run scalar fitness is averaged over fixed seeds. Define aggregation within each run explicitly.",
    "evaluation_count": "Number of episodes (environment) or independent seeded runs (batch), 1..10000",
    "timeout_seconds": "Maximum wall time per episode or seeded batch run, 1..21600; an exceeded limit must appear as timeout",
    "total_timeout_seconds": "Maximum wall time for the complete evaluation, 1..604800. Remaining seeds are timeout records when this total is reached.",
    "max_steps": "Positive episode step limit, or null for no step limit; timeout still applies",
    "horizon_policy": "require_termination (default): step-limit truncation is incomplete; fixed_horizon: reaching exactly max_steps completes a finite-horizon evaluation and scores its return. Early truncation and wall-time limits remain failures.",
    "adapter_entrypoint": "Included gym_adapter:evaluate for Gymnasium, otherwise a researcher-supplied module:function",
    "source_revision": "Frozen repository commit, dataset digest, or precise dataset/environment release",
    "dependencies": "Versioned dependency/environment specification; a lock file with SHA-256 is mandatory with each result",
    "failure_policy": "zero for success/accuracy only; fail_run for other metrics",
    "seed_start": "Optional integer; default 1000000. Visible fixed evaluation seed range.",
    "seed_end": "Optional integer; default 999999999. Server samples unique fixed seeds once per contract version.",
    "environment_imports": "Optional list of package names that register Gymnasium environments",
    "environment_kwargs": "Optional JSON object passed to gym.make; explicitly set built-in episode limits where needed",
    "seed_method": "reset for reset(seed=seed), core_disp for explicit core/disp seed API",
    "baseline": "Optional scientific reference; reported source scores are not reproduced results",
}
INTRO = ("Which BOLD OS project is this evaluation for? Paste its project page link and describe the problem. You can add a paper and a GitHub repository. "
         "I will read them, propose a short evaluation contract, and ask only for missing decisions. "
         "You approve the contract before it becomes the agreed experiment.")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def reference(value):
    """A provenance reference is metadata; the service never opens local paths."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or any(ord(c) < 32 for c in value):
        raise ValueError("Provide a nonempty artifact or code reference.")
    if value.startswith("local:") and value[6:].strip():
        return
    sources.source_syntax(value)


def initial():
    return {"contract": {}, "messages": [{"id": secrets.token_hex(8), "role": "assistant", "content": INTRO}],
            "sources": [], "proposal": None, "history": [], "results": [], "status": "idle", "stage": "Start your experiment",
            "error": None, "open_decisions": [], "model_calls": 0, "requests": {}, "job_id": None, "round": 1, "round_start": 0}


def require_member(access, request):
    """Apply the configured Lite access policy without changing project ownership."""
    if not access.enabled:
        return
    if access.is_admin(request):
        return
    identity = access.user(request)
    policy = os.getenv("AUTOKAGGLE_LITE_ACCESS_POLICY", "members")
    if policy not in {"members", "verified_email"}:
        raise HTTPException(503, "Lite access is not configured correctly. Contact the administrator.")
    if policy == "verified_email":
        if identity and identity.get("email"):
            return
        raise HTTPException(401, "Sign in with your email to use AutoKaggle Lite.")
    allowed = {email.strip().lower() for email in os.getenv("AUTOKAGGLE_LITE_MEMBERS", "").split(",") if email.strip()}
    if not identity or identity.get("email", "").lower() not in allowed:
        raise HTTPException(403, "AutoKaggle Lite is for approved lab members. Ask an administrator to add your account.")


def bold_project_id(value):
    """Validate a project reference. BOLD OS checks existence when registering."""
    from urllib.parse import urlsplit, parse_qs
    try:
        url = urlsplit(value)
        fields = parse_qs(url.fragment, strict_parsing=True)
        ids = fields.get("id", [])
        if (url.scheme != "https" or url.netloc != "bold-lab-ai.github.io"
                or url.path != "/bold-os/project.html" or url.query
                or set(fields) - {"id", "tab", "board"} or len(ids) != 1
                or any(len(values) != 1 for values in fields.values())
                or ("board" in fields and not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", fields["board"][0]))
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", ids[0])):
            raise ValueError()
        return ids[0]
    except (ValueError, TypeError):
        raise ValueError("Paste the BOLD OS project page link, with #id=<project-id>. A project name or repository link is not enough.") from None


def clean_contract(value):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError("Use the supported Lite contract fields.")
    result = {}
    for key, val in value.items():
        if val == "" or (val is None and key != "max_steps"):
            continue
        if key in STRINGS:
            if not isinstance(val, str) or len(val) > 4000:
                raise ValueError(f"{key}: use text up to 4000 characters.")
            val = val.strip()
            if not val:
                continue
        elif key in ENUMS:
            if val not in ENUMS[key]:
                raise ValueError(f"{key}: choose from {', '.join(sorted(ENUMS[key]))}.")
        elif key in INTS:
            if key == "max_steps" and val is None:
                pass
            elif type(val) is not int or not INTS[key][0] <= val <= INTS[key][1]:
                raise ValueError(f"{key}: use an integer between {INTS[key][0]} and {INTS[key][1]}.")
        elif key == "environment_imports":
            if not isinstance(val, list) or len(val) > 10 or any(not isinstance(p, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.\w+)*", p) for p in val):
                raise ValueError("Use at most ten Python module names for environment imports.")
        elif key == "environment_kwargs":
            if not isinstance(val, dict) or len(json.dumps(val, allow_nan=False)) > 4000:
                raise ValueError("Environment arguments must be a small JSON object.")
        result[key] = val
    if result.get("bold_project_url"):
        bold_project_id(result["bold_project_url"])
    if result.get("source_url"):
        reference(result["source_url"])
    if result.get("adapter_entrypoint") and not re.fullmatch(r"[A-Za-z_]\w*(?:\.\w+)*:[A-Za-z_]\w*", result["adapter_entrypoint"]):
        raise ValueError("Use module:function for the adapter entry point.")
    if result.get("task_kind") == "environment" and result.get("artifact_type") not in {None, "policy", "checkpoint", "code"}:
        raise ValueError("Environment evaluation requires a policy, checkpoint, or code artifact.")
    if result.get("failure_policy") == "zero" and result.get("metric") not in {None, "success_rate", "accuracy"}:
        raise ValueError("Use fail_run for error or unbounded score metrics. Zero could reward a failed run.")
    if result.get("horizon_policy") == "fixed_horizon" and (result.get("task_kind") != "environment" or not result.get("max_steps")):
        raise ValueError("A fixed horizon requires an environment task and a positive max_steps value.")
    start, end = result.get("seed_start", 1000000), result.get("seed_end", 999999999)
    if end < start or end - start + 1 < result.get("evaluation_count", 1):
        raise ValueError("The seed range must contain enough distinct evaluation seeds.")
    return result


def clean_decisions(value):
    if not isinstance(value, list) or len(value) > len(FIELDS):
        raise ValueError("Open decisions must be a list of contract fields and reasons.")
    checked = {}
    for decision in value:
        if (not isinstance(decision, dict) or set(decision) != {"field", "reason"}
                or decision["field"] not in FIELDS or not isinstance(decision["reason"], str)
                or not decision["reason"].strip() or len(decision["reason"]) > 1000):
            raise ValueError("Each open decision needs a supported field and a short reason.")
        if decision["field"] not in {"baseline", "title"}:
            checked[decision["field"]] = {"field": decision["field"], "reason": decision["reason"].strip()}
    return list(checked.values())


def checklist(contract, open_decisions=None):
    decisions = {item["field"]: item["reason"] for item in clean_decisions(open_decisions or [])}
    extra_groups = {"env_id": "submission", "environment_imports": "sources", "environment_kwargs": "sources",
                    "seed_method": "submission", "success_key": "submission", "max_steps": "evaluation",
                    "horizon_policy": "evaluation", "seed_start": "evaluation", "seed_end": "evaluation"}
    groups = []
    for key, title, fields in GROUPS:
        fields = list(fields)
        if key == "evaluation" and contract.get("metric") == "custom":
            fields += ["metric_name", "metric_definition", "metric_direction"]
        if key == "evaluation":
            specific = {"optimization": "constraints", "forecasting": "temporal_policy", "generation": "generation_policy", "custom": "metric_definition"}
            extra = specific.get(contract.get("task_kind"))
            if extra and extra not in fields:
                fields.append(extra)
        if key == "evaluation" and contract.get("task_kind") == "environment":
            fields.append("max_steps")
        if key == "submission" and contract.get("adapter_entrypoint") == "gym_adapter:evaluate":
            fields += ["env_id", "seed_method"]
            if contract.get("metric") == "success_rate":
                fields.append("success_key")
        fields += [field for field in decisions if field not in fields and extra_groups.get(field) == key
                   and not any(field in required for _, _, required in GROUPS)]
        missing = [field for field in fields if field not in contract or field in decisions]
        groups.append({"id": key, "title": title, "resolved": len(fields)-len(missing), "total": len(fields),
                       "missing": missing, "summary": " · ".join(str(contract[f]) for f in fields if f in contract)[:700],
                       "open_decisions": [{"field": field, "reason": decisions[field]} for field in fields if field in decisions],
                       "fields": {f: contract.get(f) for f in fields}})
    return groups


def ready(contract, open_decisions=None):
    return not clean_decisions(open_decisions or []) and all(not group["missing"] for group in checklist(contract))


def version(contract, records):
    return _hash({"format": FORMAT, "contract": contract,
        "evaluator_files": evaluator_files(),
        "package_generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sources": [{k: r[k] for k in ("kind", "url", "commit", "sha256") if k in r} for r in records]})[:24]


def evaluator_files():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("lite_runner.py", "lite_gym_adapter.py", "lite_quality.py")}


def view(project):
    from . import lite_providers
    state = project["lite"]
    current_version = version(state["contract"], state["sources"])
    built = state.get("package")
    package = {"status": "not_built"}
    if built:
        package = {**built, "status": "ready" if built["version"] == current_version and built.get("decision_history_sha256") == _hash(state.get("history", [])) and not state.get("proposal") and ready(state["contract"], state.get("open_decisions")) else "stale"}
        if package["status"] == "ready":
            base = f"/api/projects/{project['id']}/lite"
            package.update(url=base+"/package", preview_url=base+"/preview", readme_url=base+"/readme.md", config_url=base+"/config")
    return {"id": project["id"], "title": project["title"],
            **{k: copy.deepcopy(state.get(k)) for k in ("status", "stage", "error", "messages", "contract", "proposal", "results")},
            "evidence": copy.deepcopy(state.get("accepted_evidence", {})),
            "open_decisions": copy.deepcopy(state.get("open_decisions", [])),
            "checklist": checklist(state["contract"], state.get("open_decisions")), "ready": ready(state["contract"], state.get("open_decisions")) and not state.get("proposal"),
            "sources": [{k: r[k] for k in ("kind", "url", "title", "commit", "sha256", "truncated") if k in r} for r in state["sources"]],
            "package": package, "model": {"configured": bool(lite_providers.key()),
                "name": lite_providers.model(), "calls": state["model_calls"],
                "round_calls": state["model_calls"]-state.get("round_start", 0), "limit": 30}}


def model_schema():
    return {"type": "object", "additionalProperties": False, "properties": {
        "summary": {"type": "string"}, "question": {"type": "string"}, "question_field": {"type": "string", "enum": ["", *sorted(FIELDS)]},
        "open_decisions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"field": {"type": "string", "enum": sorted(FIELDS)}, "reason": {"type": "string"}},
            "required": ["field", "reason"]}},
        "resolved_decisions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"field": {"type": "string", "enum": sorted(FIELDS)}, "reason": {"type": "string"}},
            "required": ["field", "reason"]}},
        "updates": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"field": {"type": "string", "enum": sorted(FIELDS)}, "value_json": {"type": "string"},
                "basis": {"type": "string", "enum": ["researcher", "source", "suggestion"]}, "evidence": {"type": "string"}},
            "required": ["field", "value_json", "basis", "evidence"]}}}, "required": ["summary", "question", "question_field", "updates", "open_decisions", "resolved_decisions"]}


def result_context(state):
    """Give revision advice measured summaries, never full artifacts or private references."""
    current = version(state.get("contract", {}), state.get("sources", []))
    return [{"version": row["version"], "summary": copy.deepcopy(row["summary"]),
             "status_counts": {status: sum(record.get("status") == status for record in row.get("records", []))
                               for status in ("completed", "failed", "timeout", "truncated")},
             "evidence_level": row["evidence_level"], "independently_reproduced": row.get("independently_reproduced", False),
             "historical_version": row["version"] != current, "limitations": row.get("limitations", ""),
             "checks": row.get("checks", []), "received_at": row.get("received_at")}
            for row in state.get("results", [])[-3:]]


def propose(state):
    if not os.getenv("OPENROUTER_API_KEY"):
        raise ValueError("OpenRouter is not configured. Add OPENROUTER_API_KEY in the private environment file.")
    from openai import OpenAI
    current = (state.get("proposal") or {}).get("contract", state["contract"])
    open_decisions = (state.get("proposal") or {}).get("open_decisions", state.get("open_decisions", []))
    material = {"messages": state["messages"][-40:], "sources": state["sources"], "accepted_contract": state["contract"],
        "saved_result_summaries": result_context(state), "current_contract_version": version(state["contract"], state["sources"]),
        "current_proposal": current, "open_decisions": open_decisions, "missing": checklist(current, open_decisions), "contract_fields": sorted(FIELDS), "field_help": CONTRACT_HELP,
        "field_types": {**{field: {"type": "string"} for field in STRINGS},
                        **{field: {"type": "string", "enum": sorted(values)} for field, values in ENUMS.items()},
                        **{field: {"type": "integer or null" if field == "max_steps" else "integer", "minimum": bounds[0], "maximum": bounds[1]} for field, bounds in INTS.items()},
                        "environment_imports": {"type": "array of Python module names"}, "environment_kwargs": {"type": "object"}}}
    with OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1", timeout=150, max_retries=0) as client:
        response = client.chat.completions.create(model=os.getenv("AUTOKAGGLE_LITE_MODEL", "openai/gpt-6.1-sol"),
            messages=[{"role": "system", "content": (HERE / "prompts/lite.md").read_text()},
                      {"role": "user", "content": json.dumps(material, ensure_ascii=False)}],
            response_format={"type": "json_schema", "json_schema": {"name": "lite_proposal", "strict": True, "schema": model_schema()}},
            extra_body={"reasoning": {"effort": "medium"}}, max_tokens=6500)
    return parse_proposal(state, response)


def parse_proposal(state, response):
    current = (state.get("proposal") or {}).get("contract", state["contract"])
    if not response.choices or response.choices[0].finish_reason != "stop":
        raise ValueError("The model response did not finish. Your message is saved. Retry the last request.")
    try:
        parsed = json.loads(response.choices[0].message.content)
        if not {"summary", "question", "updates"} <= set(parsed) or set(parsed)-{"summary", "question", "question_field", "updates", "open_decisions", "resolved_decisions"} or not isinstance(parsed["updates"], list) or len(parsed["updates"]) > 50:
            raise ValueError
        if any(not isinstance(parsed[k], str) or len(parsed[k]) > 4000 for k in ("summary", "question")):
            raise ValueError
        candidate = copy.deepcopy(current)
        evidence = copy.deepcopy((state.get("proposal") or {}).get("evidence", {}))
        researcher_text = "\n".join(m["content"] for m in state["messages"] if m["role"] == "user")
        issues = []
        updated_fields = set()
        def strings(value):
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                return "\n".join(strings(v) for v in value.values())
            if isinstance(value, list):
                return "\n".join(strings(v) for v in value)
            return ""
        source_text = strings(state["sources"])
        for update in parsed["updates"]:
            if not isinstance(update, dict) or set(update) != {"field", "value_json", "basis", "evidence"} or update["field"] not in FIELDS:
                issues.append({"field": "unknown", "reason": "Unsupported update structure; no fact was applied."})
                continue
            basis, excerpt = update["basis"], update["evidence"]
            if not isinstance(excerpt, str) or len(excerpt) > 2000:
                issues.append({"field": update["field"], "reason": "The source evidence was invalid."})
                continue
            # Imported facts need traceable excerpts. Unsupported extraction stays a suggestion.
            if basis in {"researcher", "source"}:
                pool = researcher_text if basis == "researcher" else source_text
                if not excerpt or excerpt not in pool:
                    basis = "suggestion"
                    excerpt = "The source excerpt could not be matched. Review this proposed value."
            elif basis != "suggestion":
                issues.append({"field": update["field"], "reason": "The evidence basis was invalid."})
                continue
            field = update["field"]
            try:
                value = json.loads(update["value_json"])
            except (ValueError, TypeError):
                # Plain text in a text field is recoverable. Never guess a scientific number.
                if field in STRINGS | set(ENUMS) and isinstance(update["value_json"], str):
                    value = update["value_json"]
                else:
                    issues.append({"field": field, "reason": "The model did not supply a valid typed value."})
                    continue
            try:
                if value is None and field != "max_steps":
                    candidate.pop(field, None)
                    evidence.pop(field, None)
                    continue
                one = {field: value}
                if field == "seed_start" and type(value) is int:
                    one["seed_end"] = max(value, 999999999)
                elif field == "seed_end":
                    one["seed_start"] = 0
                elif field == "horizon_policy":
                    one.update(task_kind="environment", max_steps=1)
                clean_contract(one)
            except (ValueError, TypeError) as exc:
                issues.append({"field": field, "reason": str(exc)})
                continue
            candidate[field] = value
            updated_fields.add(field)
            evidence[field] = {"basis": basis, "excerpt": excerpt}
            if basis == "source":
                matched = next((r for r in state["sources"] if excerpt in strings(r)), None)
                if matched:
                    evidence[field].update(source_url=matched.get("url"), source_revision=matched.get("commit", matched.get("sha256")))
        # Resolve only invalid combinations. Preserve all independent valid extraction.
        if candidate.get("task_kind") == "environment" and candidate.get("artifact_type") not in {None, "policy", "checkpoint", "code"}:
            candidate.pop("artifact_type", None)
            issues.append({"field": "artifact_type", "reason": "Choose a policy or checkpoint for an environment task."})
        if candidate.get("failure_policy") == "zero" and candidate.get("metric") not in {None, "success_rate", "accuracy"}:
            candidate.pop("failure_policy", None)
            issues.append({"field": "failure_policy", "reason": "Zero can reward a failed error-metric run. Choose fail_run."})
        if candidate.get("horizon_policy") == "fixed_horizon" and (candidate.get("task_kind") != "environment" or not candidate.get("max_steps")):
            candidate.pop("horizon_policy", None)
            issues.append({"field": "horizon_policy", "reason": "A fixed horizon requires an environment task and a positive max_steps value."})
        start, end = candidate.get("seed_start", 1000000), candidate.get("seed_end", 999999999)
        if end < start or end-start+1 < candidate.get("evaluation_count", 1):
            candidate.pop("seed_start", None)
            candidate.pop("seed_end", None)
            issues.append({"field": "seed_range", "reason": "The proposed seed range was too small. The visible default range is proposed for review."})
        candidate = clean_contract(candidate)
        prior_decisions = clean_decisions((state.get("proposal") or {}).get("open_decisions", state.get("open_decisions", [])))
        decisions = clean_decisions(parsed.get("open_decisions", prior_decisions))
        resolutions = clean_decisions(parsed.get("resolved_decisions", []))
        resolved = {item["field"] for item in resolutions if item["field"] in updated_fields and item["field"] in candidate}
        assessed = {item["field"] for item in decisions}
        # A compatible update or an omitted assessment must not erase a saved gap.
        decisions += [item for item in prior_decisions if item["field"] not in assessed and item["field"] not in resolved]
    except (ValueError, TypeError, KeyError):
        raise ValueError("The model returned an invalid contract. Your accepted answers are safe. Retry or edit the proposal.") from None
    missing = [f for group in checklist(candidate, decisions) for f in group["missing"]]
    question = parsed["question"]
    question_field = parsed.get("question_field", "")
    if question_field not in FIELDS:
        question_field = missing[0] if missing else ""
    if missing and (not question or re.search(r"review.{0,50}(accept|correct)|accept.{0,30}(contract|definition)", question, re.I)):
        question_field = missing[0]
        prompts = {
            "source_url": "Does evaluation need external data or code, or is the full problem defined in this conversation? This determines what a collaborator must retrieve.",
            "source_revision": "Which fixed version of the source should we use? A commit, dataset digest, or versioned definition keeps later scores comparable.",
            "compute_budget": "What hardware and time limit should an attempt use? This makes resource use comparable.",
            "dependencies": "Which software versions should the evaluator use? A fixed environment is needed to repeat the score."
        }
        question = prompts.get(question_field, "What should we record for " + question_field.replace("_", " ") + "? This is needed to run or interpret the evaluation.")
    if decisions and not question:
        question_field = decisions[0]["field"]
        question = "Please resolve " + question_field.replace("_", " ") + ": " + decisions[0]["reason"]
    if issues:
        question = "Please confirm " + missing[0].replace("_", " ") + "; this is still needed to run or interpret the evaluation." if missing else "Please review the proposed contract and the extraction notes before accepting it."
        question_field = missing[0] if missing else ""
    key = question_field + ":" + _hash(candidate.get(question_field))
    if question_field and state.get("question_counts", {}).get(key, 0) >= 2:
        question = "This decision still needs your review: " + question_field.replace("_", " ") + ". Edit its value in the proposed contract, or keep it open. The package stays a draft until it is defined."
    return {"id": secrets.token_hex(12), "contract": candidate, "evidence": evidence, "validation_notes": issues, "open_decisions": decisions, "resolved_decisions": resolutions,
            "summary": ("The definition is still a draft. " + parsed["summary"] if missing and re.search(r"complete|ready", parsed["summary"], re.I) else parsed["summary"]), "question": question, "question_field": question_field, "question_key": key, "created_at": now(),
            "model": response.model, "usage": response.usage.model_dump() if response.usage else None}


def readme(project, contract_record):
    c = contract_record["contract"]
    lines = ["# " + c.get("title", project["title"]), "", "BOLD AutoKaggle Lite — internal research", "",
             "This package defines a trusted, researcher-run experiment. It does not establish independent reproduction.", "",
             "Contract version: `"+contract_record["version"]+"`", "",
             "## Research contract", ""]
    for _, title, fields in GROUPS:
        lines += ["### " + title, ""]
        for field in fields:
            lines += [f"- **{field.replace('_', ' ')}:** {c.get(field, 'Not defined')}"]
        lines += [""]
    extras = {field: c[field] for field in ("env_id", "environment_imports", "environment_kwargs", "success_key", "seed_method", "max_steps", "horizon_policy", "metric_name", "metric_definition", "metric_direction", "constraints", "temporal_policy", "generation_policy") if field in c}
    if extras:
        lines += ["## Adapter configuration", "", "```json", json.dumps(extras, indent=2), "```", ""]
    lines += ["The fixed seed list and evaluator file hashes are in contract.json. Keep that file unchanged with each result.", ""]
    lines += ["## Run the experiment", "",
        "1. Check out the declared code revision and install its fixed dependencies in an isolated local environment.",
        "2. Review the local adapter code. The web service does not run it. For Gymnasium use the included gym_adapter.py. Other tasks must implement adapter:evaluate as shown in adapter.py.",
        "3. Copy manifest.example.json to manifest.json. Set the code repository and full commit, artifact path and SHA-256, policy loader, dependency lock path and SHA-256, and actual resource settings.",
        "4. Run `python run.py --manifest manifest.json --output results.json` from the researcher code directory. Use the full path to run.py if the package is elsewhere.",
        "5. Submit the JSON result bundle through the Lite results control. Include every assigned seed, including failed or timed-out runs.", "",
        "The artifact can be a checkpoint or predictions, as declared. A policy loader receives the artifact path and returns an object with act(observation), with optional reset().", "",
        "Each seed starts a fresh process. The timeout covers imports, reset, inference, and environment steps. This runner is for trusted lab code. It is not a security sandbox or a hardware quota service.", "",
        "The seed list is fixed for this contract version and visible to researchers. It is not a blind holdout. Dataset or answer exposure is recorded separately. Do not interpret repeat evaluation as evidence against prior test exposure.", "",
        "The default horizon policy requires natural termination. An explicit fixed_horizon policy scores an episode when it reaches exactly max_steps. Early truncation, timeouts, and process failures remain failures. The contract selects either zero contribution or an incomplete run. No failed result can be omitted.", "",
        "## Evidence levels", "",
        "- researcher_reported: submitted results before validation.",
        "- evidence_checked: the service checked the contract version, required provenance fields, seed coverage, finite scores, and declared failure rules. It did not rerun the model or fetch the checkpoint.",
        "- independently_reproduced: reserved for a separate controlled rerun. This version of Lite cannot grant that status.", "",
        "Reproduction of an evaluation score does not establish the reported training procedure or training cost.", "",
        "## Sources", ""]
    for source in contract_record["sources"]:
        lines += [f"- {source.get('url', 'Uploaded paper')}; revision or digest: {source.get('commit', source.get('sha256', 'unknown'))}"]
    if c.get("baseline"):
        lines += ["", "## Optional reference", "", c["baseline"], "", "This reference has not been reproduced by package generation."]
    lines += ["", "## Changes", "", "A correction creates a new contract version. Rebuild the package and run that version. Earlier results remain attached to their original version.", ""]
    return "\n".join(lines)


def build(project, directory):
    state, c = project["lite"], clean_contract(project["lite"]["contract"])
    if state.get("proposal"):
        raise ValueError("Review and accept or discard the pending proposal before building.")
    if not ready(c, state.get("open_decisions")):
        missing = [f for group in checklist(c, state.get("open_decisions")) for f in group["missing"]]
        raise ValueError("Resolve these contract fields first: " + ", ".join(missing))
    revision = version(c, state["sources"])
    seeds = random.Random(int(revision, 16)).sample(range(c.get("seed_start", 1000000), c.get("seed_end", 999999999)+1), c["evaluation_count"])
    records = [{k: r[k] for k in ("kind", "url", "commit", "sha256", "truncated") if k in r} for r in state["sources"]]
    record = {"format": FORMAT, "version": revision, "contract": c, "seeds": seeds, "sources": records,
              "evaluator_files": evaluator_files(),
              "package_generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "seed_exposure": "visible", "execution": "researcher_local", "evidence_policy": "reported_then_structure_checked"}
    record["contract_sha256"] = _hash(record)
    manifest = {"format": "bold.autokaggle.lite.submission.v1", "challenge_version": revision,
                "code_repository": c["source_url"], "code_revision": "REPLACE_WITH_FULL_COMMIT", "code_directory": ".",
                "artifact_url": "https://example.org/model-or-predictions", "artifact_path": "model.bin",
                "artifact_sha256": "REPLACE_WITH_SHA256", "policy_loader": "policy:load", "contract_sha256": record["contract_sha256"],
                "dependencies_path": "requirements.lock", "dependencies_sha256": "REPLACE_WITH_SHA256",
                "resources": c["compute_budget"], "training_provenance": "Record training code, data versions, seeds, and resource use here."}
    schema = {"format": "bold.autokaggle.lite.results.v1", "challenge_version": revision, "manifest": manifest,
              "results": [{"seed": seeds[0], "status": "completed", "score": 0.0, "steps": 1}],
              "note": "Include exactly one record for every seed in contract.json. Never upload this example as a measured result."}
    result_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        "required": ["format", "challenge_version", "manifest", "results"], "properties": {
            "format": {"const": "bold.autokaggle.lite.results.v1"}, "challenge_version": {"const": revision},
            "manifest": {"$ref": "manifest.schema.json"}, "results": {"type": "array", "minItems": len(seeds), "maxItems": len(seeds),
                "items": {"type": "object", "required": ["seed", "status", "score", "steps"], "properties": {
                    "seed": {"type": "integer", "enum": seeds}, "status": {"enum": ["completed", "failed", "timeout", "truncated"]},
                    "score": {"type": ["number", "null"]}, "steps": {"type": "integer", "minimum": 0},
                    "end_reason": {"enum": ["terminated", "evaluation_horizon", "environment_truncated", "step_limit"]}}}}},
        "$comment": "The server additionally checks each seed appears once, metric bounds, failure rules, and the current contract version."}
    manifest_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        "required": ["format", "challenge_version", "contract_sha256", "code_repository", "code_revision", "artifact_url",
                     "artifact_sha256", "dependencies_path", "dependencies_sha256", "resources", "training_provenance"],
        "properties": {"format": {"const": "bold.autokaggle.lite.submission.v1"}, "challenge_version": {"const": revision},
            "contract_sha256": {"const": record["contract_sha256"]}, "code_revision": {"type": "string", "pattern": "^[a-f0-9]{40}$"},
            "artifact_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "dependencies_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}
    text = readme(project, record)
    agents = ("# Internal research rules\n\nFollow contract.json and the README. Use only the declared data, files, tools, and services. "
              "Do not search for hidden answers, embed answer tables, access scorer secrets, or infer answers through repeated score queries. "
              "The fixed seeds in this Lite package are visible. Record all test-answer exposure and all attempts, including failures. "
              "Keep code, checkpoint, dependency, data, and contract versions with each result. Do not call a submitted result independently reproduced. "
              "These instructions do not enforce restrictions on a local machine. Paid compute and hosted jobs require separate authorization.\n")
    adapter = '''"""Implement this adapter for a batch task or another environment."""\ndef evaluate(seed, manifest, contract):\n    # Load the exact artifact and dataset, run the declared protocol, and return:\n    # {"seed": seed, "status": "completed", "steps": 1, "score": measured_score}\n    # Failed/truncated records use score=None. Never return a made-up score.\n    raise NotImplementedError("Implement and test the declared evaluation protocol before reporting results.")\n'''
    package_dir = Path(directory) / "lite" / revision
    package_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = {"README.md": text, "AGENTS.md": agents, "contract.json": json.dumps(record, indent=2),
             "manifest.example.json": json.dumps(manifest, indent=2), "results.example.json": json.dumps(schema, indent=2),
             "manifest.schema.json": json.dumps(manifest_schema, indent=2), "results.schema.json": json.dumps(result_schema, indent=2),
             "decision-evidence.json": json.dumps(state.get("accepted_evidence", {}), indent=2),
             "run.py": (HERE / "lite_runner.py").read_text(), "gym_adapter.py": (HERE / "lite_gym_adapter.py").read_text(),
             "quality_checks.py": (HERE / "lite_quality.py").read_text(),
             "adapter.py": adapter, "ENVIRONMENT.md": "# Declared evaluation environment\n\n"+c["dependencies"]+"\n\n"
                 "This is the agreed environment specification. It is not a generated dependency lock. "
                 "Use the researcher repository's fixed dependency lock and record its SHA-256 in the submission manifest. "
                 "The base runner uses the Python standard library. The selected adapter and policy can require additional dependencies.\n"}
    with zipfile.ZipFile(package_dir / "research.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    (package_dir / "README.md").write_text(text)
    (package_dir / "contract.json").write_text(json.dumps(record, indent=2))
    state["package"] = {"version": revision, "built_at": now(), "execution_status": "not_run", "seed_count": len(seeds),
                        "decision_history_sha256": _hash(state.get("history", []))}
    history = state.setdefault("package_history", [])
    if not any(p["version"] == revision for p in history):
        history.append(copy.deepcopy(state["package"]))
    return state["package"]


def record_results(project, directory, request_id, manifest, records):
    state = project["lite"]
    package = view(project)["package"]
    revision = manifest.get("challenge_version") if isinstance(manifest, dict) else None
    saved_versions = {p["version"] for p in state.get("package_history", [])}
    if state.get("package"):
        saved_versions.add(state["package"]["version"])
    if revision not in saved_versions or not re.fullmatch(r"[a-f0-9]{24}", str(revision)):
        raise ValueError("Build and use an accepted contract version before submitting results.")
    contract_record = json.loads((Path(directory) / "lite" / revision / "contract.json").read_text())
    submitted_contract = contract_record["contract"]
    if not isinstance(manifest, dict) or manifest.get("challenge_version") != revision:
        raise ValueError("The submission manifest must name the current challenge version.")
    if len(json.dumps(manifest, allow_nan=False)) > 32000:
        raise ValueError("Keep the submission manifest below 32,000 characters. Use artifact references for large content.")
    if manifest.get("contract_sha256") != contract_record["contract_sha256"]:
        raise ValueError("The submission manifest must contain the unchanged package contract digest.")
    if manifest.get("format") != "bold.autokaggle.lite.submission.v1":
        raise ValueError("Use the submission manifest format from the package.")
    for field in ("artifact_sha256", "dependencies_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get(field, ""))):
            raise ValueError(f"{field}: provide a SHA-256 digest.")
    if not re.fullmatch(r"[a-f0-9]{40}", str(manifest.get("code_revision", ""))):
        raise ValueError("Provide the complete 40-character code commit.")
    reference(manifest.get("code_repository", ""))
    for field in ("artifact_url", "resources", "training_provenance", "dependencies_path"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip() or len(manifest[field]) > 4000:
            raise ValueError(f"Provide {field} in the submission manifest.")
    reference(manifest["artifact_url"])
    if submitted_contract["artifact_type"] in {"policy", "checkpoint"} and not re.fullmatch(r"[A-Za-z_]\w*(?:\.\w+)*:[A-Za-z_]\w*", str(manifest.get("policy_loader", ""))):
        raise ValueError("Provide the policy loader as module:function.")
    if not isinstance(records, list) or len(records) != len(contract_record["seeds"]):
        raise ValueError("Include every assigned seed exactly once, including failed runs.")
    by_seed = {}
    normalized = []
    for record in records:
        if not isinstance(record, dict) or type(record.get("seed")) is not int or record["seed"] in by_seed:
            raise ValueError("Result records need distinct integer seeds.")
        by_seed[record["seed"]] = True
        from .lite_quality import validate_metadata
        validate_metadata(record)
        checked = validate_record(copy.deepcopy(record), record["seed"], submitted_contract["metric"])
        if checked.get("end_reason") == "evaluation_horizon" and (submitted_contract.get("horizon_policy") != "fixed_horizon" or checked["steps"] != submitted_contract.get("max_steps")):
            raise ValueError("A horizon result must reach the declared fixed horizon.")
        if submitted_contract.get("max_steps") is not None and checked["steps"] > submitted_contract["max_steps"]:
            raise ValueError("The reported steps exceed the declared episode limit.")
        elapsed = checked.get("elapsed_seconds")
        if elapsed is not None:
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("Reported elapsed time must be finite and nonnegative.")
            if checked["status"] == "completed" and elapsed > submitted_contract["timeout_seconds"] + 0.1:
                raise ValueError("A completed record exceeds the per-run time limit. Record it as a timeout.")
        normalized.append(checked)
    if set(by_seed) != set(contract_record["seeds"]):
        raise ValueError("The result seeds must match the current fixed evaluation set.")
    fingerprint = _hash([manifest, normalized])
    for previous in state["results"]:
        if previous["request_id"] == request_id:
            if previous["fingerprint"] != fingerprint:
                raise ValueError("This request ID already belongs to different result evidence.")
            return previous
    if len(state["results"]) >= 100:
        raise ValueError("This internal session has reached its 100-result limit.")
    result = {"id": secrets.token_hex(12), "request_id": request_id, "fingerprint": fingerprint,
              "version": revision, "manifest": copy.deepcopy(manifest), "records": normalized,
              "evidence_level": "evidence_checked", "independently_reproduced": False, "received_at": now(),
              "historical_version": package.get("version") != revision or package["status"] != "ready",
              "checks": ["contract version", "manifest fields", "artifact and dependency hash syntax", "complete seed coverage", "finite metrics", "failure policy"],
              "limitations": "The service did not fetch the artifact, verify the declared commit, run the model, or verify training provenance.",
              "summary": summarize(normalized, submitted_contract)}
    state["results"].append(result)
    return result


class Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=180)
    organizer_email: str = Field(max_length=254)
    storage_accepted: bool


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=100)


class Message(Action):
    message: str = Field(min_length=1, max_length=12000)


class Import(Action):
    paper_url: str = Field(default="", max_length=2000)
    repository_url: str = Field(default="", max_length=2000)
    brief: str = Field(default="", max_length=12000)


class Accept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=1, max_length=100)
    contract: dict[str, Any] | None = None


class Results(Action):
    manifest: dict[str, Any]
    results: list[dict[str, Any]] = Field(max_length=10000)


def register(app, store, pool, access, get, editing):
    def lite_get(identifier, request):
        item = get(identifier, request)
        if "lite" not in item:
            raise HTTPException(404, "This is not an internal Lite session. Create a separate Lite session.")
        return item

    def change(identifier, request, callback):
        lite_get(identifier, request)
        with editing(identifier, request) as item:
            if item["lite"]["status"] == "working":
                raise HTTPException(409, "The agent is working. Wait for its saved response.")
            try:
                result = callback(item)
            except (ValueError, TypeError) as exc:
                raise HTTPException(422, str(exc)) from exc
            store.save(item)
            return result if result is not None else view(item)

    def reload(identifier):
        with store.connection() as con:
            row = con.execute("SELECT body FROM projects WHERE id=?", (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def work(identifier, job_id, task):
        item = reload(identifier)
        if not item or item.get("lite", {}).get("job_id") != job_id:
            return
        try:
            state = item["lite"]
            records = copy.deepcopy(state["sources"])
            if task.get("paper_url"):
                records.append(sources.paper(task["paper_url"]))
            if task.get("repository_url"):
                from . import repository_store
                def progress(stage):
                    with store.lock(identifier):
                        fresh = reload(identifier)
                        if fresh and fresh["lite"].get("job_id") == job_id:
                            fresh["lite"]["stage"] = stage
                            store.save(fresh)
                records.append(repository_store.snapshot(task["repository_url"], store.directory(identifier), progress=progress))
            # Save fetched sources before a provider failure, so retry can reuse them.
            unique = {}
            for record in records:
                unique[(record["kind"], record.get("url"), record.get("sha256"), record.get("commit"))] = record
            if len(unique) > 12:
                raise ValueError("Use at most twelve source records in one internal session.")
            with store.lock(identifier):
                item = reload(identifier)
                if not item or item.get("lite", {}).get("job_id") != job_id:
                    return
                state = item["lite"]
                state["sources"] = list(unique.values())
                state["stage"] = "Reading sources and preparing a contract"
                store.save(item)
            model_state = copy.deepcopy(state)
            model_state["_repository_directory"] = str(store.directory(identifier))
            proposal = propose(model_state)
            with store.lock(identifier):
                item = reload(identifier)
                if not item or item.get("lite", {}).get("job_id") != job_id:
                    return
                state = item["lite"]
                state.update(proposal=proposal, status="idle", error=None, stage="Review the proposed contract")
                if proposal.get("question_field"):
                    counts = state.setdefault("question_counts", {})
                    counts[proposal["question_key"]] = counts.get(proposal["question_key"], 0) + 1
                content = proposal["summary"] + ("\n\n" + proposal["question"] if proposal["question"] else "")
                state["messages"].append({"id": secrets.token_hex(8), "role": "assistant", "content": content})
                store.save(item)
        except Exception as exc:
            with store.lock(identifier):
                item = reload(identifier)
                if not item or item.get("lite", {}).get("job_id") != job_id:
                    return
                state = item["lite"]
                state.update(status="error", stage="Saved; retry is available",
                    error=str(exc) if type(exc) is ValueError else "The source or model service did not finish. Your saved answers are safe. Retry the last request.")
                store.save(item)

    def queue(identifier, request, body, task):
        lite_get(identifier, request)
        with editing(identifier, request) as item:
            state = item["lite"]
            fingerprint = _hash(task)
            previous = state["requests"].get(body.request_id)
            if previous:
                if previous != fingerprint:
                    raise HTTPException(409, "This request ID belongs to another action.")
                return view(item)
            if state["status"] == "working":
                raise HTTPException(409, "The agent is working. Wait for its response.")
            if state["model_calls"] - state.get("round_start", 0) >= 30:
                raise HTTPException(429, "This round reached 30 model requests. Start another round to continue with the saved answers.")
            if len(state["requests"]) >= 250:
                raise HTTPException(429, "This session reached its 250-action limit.")
            state["requests"][body.request_id] = fingerprint
            text = task.get("message") or task.get("brief")
            if text:
                state["messages"].append({"id": secrets.token_hex(8), "role": "user", "content": text.strip()})
            state.update(status="working", stage="Preparing the next response", error=None, job_id=secrets.token_hex(16), last_task=task)
            state["model_calls"] += 1
            store.save(item)
            result, job_id = view(item), state["job_id"]
        pool.submit(work, identifier, job_id, task)
        return result

    @app.get("/lite")
    def page(request: Request):
        if not access.can_open(request, store):
            path = "/lite" + ("?"+request.url.query if request.url.query else "")
            return RedirectResponse("/login?next=" + quote(path, safe=""), status_code=303)
        require_member(access, request)
        return FileResponse(HERE / "static/lite.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/lite/projects")
    def projects(request: Request):
        require_member(access, request)
        owner = access.owner(request)
        return {"projects": [p for p in store.list(owner) if "lite" in (store.get(p["id"], owner) or {})]}

    @app.post("/api/lite/projects")
    def create(body: Create, request: Request, response: Response):
        access.require_create(request)
        require_member(access, request)
        if not body.storage_accepted:
            raise HTTPException(428, "Accept data storage before creating an internal session.")
        organizer = access.owner(request)
        if not organizer or not 32 <= len(organizer) <= 100:
            organizer = secrets.token_urlsafe(32)
            response.set_cookie("autokaggle_owner", organizer, httponly=True, samesite="lax", secure=access.secure_cookie(request), max_age=60*60*24*90)
        # Validate contact before creating a record.
        try:
            email = onboarding_setup.validate_email(body.organizer_email)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        item = store.create(organizer, body.title or "New internal experiment")
        item["setup"] = {**onboarding_setup.defaults(), "organizer_email": email}
        item["lite"] = initial()
        item["_storage_consent"] = {"version": workspace.POLICY_VERSION, "accepted_at": now(), "accepted_by": hashlib.sha256(organizer.encode()).hexdigest()}
        store.save(item)
        return view(item)

    @app.get("/api/projects/{project_id}/lite")
    def read(project_id: str, request: Request):
        return view(lite_get(project_id, request))

    @app.post("/api/projects/{project_id}/lite/message")
    def message(project_id: str, body: Message, request: Request):
        if not body.message.strip():
            raise HTTPException(422, "Write a message first.")
        return queue(project_id, request, body, {"message": body.message.strip()})

    @app.post("/api/projects/{project_id}/lite/import")
    def import_sources(project_id: str, body: Import, request: Request):
        item = lite_get(project_id, request)
        if not body.paper_url and not body.repository_url and not item["lite"]["sources"]:
            raise HTTPException(422, "Add a paper link, repository link, or PDF first.")
        try:
            if body.paper_url:
                sources.source_syntax(body.paper_url)
            if body.repository_url:
                sources.parse_repository(body.repository_url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return queue(project_id, request, body, body.model_dump(exclude={"request_id"}))

    @app.post("/api/projects/{project_id}/lite/attachments")
    def upload_attachment(project_id: str, request: Request, file: UploadFile = File(...)):
        from . import documents
        item = lite_get(project_id, request)
        try:
            if item["lite"]["status"] == "working":
                raise HTTPException(409, "The agent is working. Wait before adding another attachment.")
            data = file.file.read(documents.MAX_DOCUMENT_BYTES + 1)
            if not data or len(data) > documents.MAX_DOCUMENT_BYTES:
                raise HTTPException(422, "Attach a nonempty file up to 50 MB. Use a shared link for larger datasets.")
            digest = hashlib.sha256(data).hexdigest()
            if any(r.get("sha256") == digest for r in item["lite"]["sources"]):
                return view(item)
            if len(item["lite"]["sources"]) >= 12:
                raise HTTPException(422, "Use at most twelve source records per session.")
            name = Path((file.filename or "attachment").replace("\\", "/")).name[:180]
            try:
                record = documents.extract(data, name)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            source = {"kind": "attachment", "url": "uploaded:" + name, "title": name,
                      "sha256": digest, "text": record["text"][:60000],
                      "truncated": record["truncated"] or len(record["text"]) > 60000, "imported_at": now()}
            def save(item):
                records = item["lite"]["sources"]
                if any(r.get("sha256") == source["sha256"] for r in records):
                    return
                if len(records) >= 12:
                    raise ValueError("Use at most twelve source records per session.")
                records.append(source)
                item["lite"]["messages"].append({"id": secrets.token_hex(8), "role": "source", "content": "Attached " + name + (" (text excerpt)" if source["truncated"] else "")})
            return change(project_id, request, save)
        finally:
            file.file.close()

    @app.post("/api/projects/{project_id}/lite/paper")
    def upload_paper(project_id: str, request: Request, file: UploadFile = File(...)):
        lite_get(project_id, request)
        try:
            data = file.file.read(sources.MAX_PAPER + 1)
            if not data.startswith(b"%PDF") or len(data) > sources.MAX_PAPER:
                raise HTTPException(422, "Use a text PDF of at most 16 MiB.")
            try:
                from .reader_process import command as reader_command
                extracted = subprocess.run(reader_command(HERE / "source_reader.py"), input=data,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True)
                record = json.loads(extracted.stdout)
                if len(record["text"].strip()) < 100:
                    raise ValueError
            except (ValueError, subprocess.SubprocessError, KeyError):
                raise HTTPException(422, "The PDF has too little readable text or exceeded extraction limits.") from None
            source = {"kind": "paper", "url": "uploaded:" + Path(file.filename or "paper.pdf").name[:180],
                      "title": Path(file.filename or "paper.pdf").name[:180], "sha256": hashlib.sha256(data).hexdigest(),
                      "text": record["text"], "truncated": record["truncated"], "imported_at": now()}
            def save(item):
                if len(item["lite"]["sources"]) >= 12:
                    raise ValueError("Use at most twelve sources per session.")
                item["lite"]["sources"].append(source)
            return change(project_id, request, save)
        finally:
            file.file.close()

    @app.post("/api/projects/{project_id}/lite/retry")
    def retry(project_id: str, body: Action, request: Request):
        item = lite_get(project_id, request)
        if item["lite"]["status"] != "error":
            raise HTTPException(409, "There is no failed request to retry.")
        # Source records and the user message were already saved.
        previous = item["lite"].get("last_task", {})
        # Re-fetch only if the previous retrieval failed; already-saved sources are reused.
        existing = {s.get("requested_url", s.get("url")) for s in item["lite"]["sources"]}
        task = {"retry": True}
        for key in ("paper_url", "repository_url"):
            if previous.get(key) and previous[key] not in existing:
                task[key] = previous[key]
        return queue(project_id, request, body, task)

    @app.post("/api/projects/{project_id}/lite/continue")
    def continue_round(project_id: str, body: Action, request: Request):
        def reset(item):
            state = item["lite"]
            if state["model_calls"] - state.get("round_start", 0) < 30:
                raise ValueError("The current round still has model requests available.")
            state["round"] += 1
            state["round_start"] = state["model_calls"]
        return change(project_id, request, reset)

    @app.post("/api/projects/{project_id}/lite/accept")
    def accept(project_id: str, body: Accept, request: Request):
        def apply(item):
            state = item["lite"]
            proposal = state.get("proposal")
            if not proposal:
                previous = state["history"][-1] if state["history"] else {}
                if previous.get("source_proposal") == body.proposal_id and (body.contract is None or clean_contract(body.contract) == previous["contract"]):
                    return
                raise ValueError("This proposal changed. Review the current proposal first.")
            if proposal["id"] != body.proposal_id:
                raise ValueError("This proposal changed. Review the current proposal first.")
            contract = clean_contract(body.contract if body.contract is not None else proposal["contract"])
            decisions = clean_decisions(proposal.get("open_decisions", state.get("open_decisions", [])))
            evidence = {**state.get("accepted_evidence", {}), **proposal["evidence"]}
            if body.contract is not None:
                decisions = [item for item in decisions if contract.get(item["field"]) == proposal["contract"].get(item["field"]) or item["field"] not in contract]
                for field, value in contract.items():
                    if value != proposal["contract"].get(field):
                        evidence[field] = {"basis": "researcher", "excerpt": "The organizer edited and accepted this value."}
            state["accepted_evidence"] = {field: evidence[field] for field in contract if field in evidence}
            state["history"].append({"at": now(), "previous_contract": state["contract"], "contract": contract,
                                     "previous_open_decisions": state.get("open_decisions", []), "open_decisions": decisions,
                                     "resolved_decisions": proposal.get("resolved_decisions", []),
                                     "source_proposal": proposal["id"], "edited": body.contract is not None, "evidence": proposal["evidence"]})
            state.update(contract=contract, open_decisions=decisions, proposal=None, error=None, status="idle", stage="Contract accepted")
            item["title"] = contract.get("title", item["title"])
            missing = [f for group in checklist(contract, decisions) for f in group["missing"]]
            text = "The contract is accepted. Build the evaluation package when ready." if not missing else "The supplied details are accepted. " + (proposal.get("question") or "The next missing detail is " + missing[0].replace("_", " ") + ".")
            state["messages"].append({"id": secrets.token_hex(8), "role": "assistant", "content": text})
        return change(project_id, request, apply)

    @app.post("/api/projects/{project_id}/lite/discard")
    def discard(project_id: str, body: Accept, request: Request):
        def apply(item):
            if not item["lite"].get("proposal") or item["lite"]["proposal"]["id"] != body.proposal_id:
                raise ValueError("This proposal is no longer current.")
            item["lite"]["proposal"] = None
        return change(project_id, request, apply)

    @app.post("/api/projects/{project_id}/lite/build")
    def prepare(project_id: str, body: Action, request: Request):
        return change(project_id, request, lambda item: (build(item, store.directory(project_id)), None)[1])

    def package_file(project_id, request, name):
        item = lite_get(project_id, request)
        package = view(item)["package"]
        if package["status"] != "ready":
            raise HTTPException(409, "Build the current accepted contract first. Earlier artifacts are stale.")
        return item, store.directory(project_id) / "lite" / package["version"] / name

    @app.get("/api/projects/{project_id}/lite/package")
    def download(project_id: str, request: Request):
        _, path = package_file(project_id, request, "research.zip")
        return FileResponse(path, filename="bold-autokaggle-lite.zip", media_type="application/zip")

    @app.get("/api/projects/{project_id}/lite/readme.md")
    def download_readme(project_id: str, request: Request):
        _, path = package_file(project_id, request, "README.md")
        return FileResponse(path, filename="README.md", media_type="text/markdown")

    @app.get("/api/projects/{project_id}/lite/config")
    def download_config(project_id: str, request: Request):
        _, path = package_file(project_id, request, "contract.json")
        return FileResponse(path, filename="contract.json", media_type="application/json")

    @app.get("/api/projects/{project_id}/lite/preview")
    def preview(project_id: str, request: Request):
        item, path = package_file(project_id, request, "README.md")
        from .lite_preview import render_preview
        return HTMLResponse(render_preview(item, path.read_text(), view(item)["package"]["version"]))

    @app.post("/api/projects/{project_id}/lite/results")
    def results(project_id: str, body: Results, request: Request):
        def save(item):
            record_results(item, store.directory(project_id), body.request_id, body.manifest, body.results)
        return change(project_id, request, save)

