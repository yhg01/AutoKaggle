"""Bounded model assistance. Only metadata crosses the model boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
from .policy import rules_advice
from .store import now

MAX_PROPOSED_UPDATES = 16


def configured():
    return bool(os.getenv("OPENAI_API_KEY")) and os.getenv("AUTOKAGGLE_MODE", "model") != "rules"


def model_name():
    return os.getenv("AUTOKAGGLE_MODEL", "gpt-6.1-sol")


def model_context(project, kind):
    # Do not serialize the project object: it contains private seeds and capabilities.
    return {"kind": kind, "title": project["title"], "brief": project["brief"],
            "answers": project["answers"], "design": project["design"],
            "dataset_metadata": project.get("dataset"), "verified_tool_results": project.get("analysis"),
            "previous_advice": [{"content": a["content"][:1800], "kind": a["kind"]} for a in project.get("advice", [])[-2:]]}


def advise(project, kind, reserve=None):
    from . import observability
    item = {"kind": kind, "mode": "rules", "content": "", "created_at": now(), "updates": [], "next_questions": []}
    if not configured():
        item["content"] = rules_advice(project, kind)
        return item
    if project.get("_model_calls", 0) >= 12:
        item["content"] = rules_advice(project, kind)
        item["notice"] = "This project reached its 12-call model limit. Rules-based checks remain available."
        return item
    # Reserve before the call. Unknown provider outcomes must still count.
    project["_model_calls"] = project.get("_model_calls", 0) + 1
    if reserve:
        reserve(project)
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"content": {"type": "string"},
                  "next_questions": {"type": "array", "items": {"type": "string"}},
                  "updates": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                      "properties": {"field": {"type": "string"}, "value": {"type": "string"}, "evidence": {"type": "string"}},
                      "required": ["field", "value", "evidence"]}}}, "required": ["content", "next_questions", "updates"]}
    try:
        from openai import OpenAI
        instructions = (Path(__file__).parent / "prompts/organizer.md").read_text()
        provider_input = json.dumps(model_context(project, kind), ensure_ascii=False)
        effort = "high" if kind == "review" else "medium"
        with observability.model_call(project, "advice_" + kind, instructions, provider_input, effort, reserve) as trace:
            with OpenAI(timeout=120, max_retries=0) as client:
                result = client.responses.create(model=model_name(), instructions=instructions,
                    input=provider_input, reasoning={"effort": effort}, max_output_tokens=6000,
                    text={"format": {"type": "json_schema", "name": "challenge_advice", "strict": True, "schema": schema}})
            trace.update(observability.response_record(result))
        if result.status != "completed" or not result.output_text:
            raise ValueError("Model did not complete")
        parsed = json.loads(result.output_text)
        if not isinstance(parsed, dict) or set(parsed) != {"content", "next_questions", "updates"}:
            raise ValueError("Invalid advice structure")
        if not isinstance(parsed.get("content"), str) or not parsed["content"].strip():
            raise ValueError("Empty advice")
        if not isinstance(parsed.get("next_questions"), list) or any(not isinstance(q, str) for q in parsed["next_questions"]):
            raise ValueError("Invalid questions")
        if not isinstance(parsed.get("updates"), list) or any(not isinstance(u, dict) or set(u) != {"field", "value", "evidence"} or any(not isinstance(v, str) for v in u.values()) for u in parsed["updates"]):
            raise ValueError("Invalid updates")
        item.update(mode="model", model=result.model, content=parsed["content"][:8000],
                    next_questions=parsed.get("next_questions", [])[:3],
                    updates=parsed.get("updates", [])[:MAX_PROPOSED_UPDATES] if kind != "review" else [])
        if result.usage:
            item["usage"] = {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}
    except Exception as exc:
        # Raw provider messages may contain supplied text or credentials.
        item["notice"] = f"The model call failed ({type(exc).__name__}). Rules-based advice is shown. You can retry."
        item["content"] = rules_advice(project, kind)
    return item


def _matched_evidence(evidence, brief):
    """Accept exact source text, with at most one added outer quote pair."""
    if not isinstance(evidence, str):
        return None
    if len(evidence) >= 8 and evidence in brief:
        return evidence
    quote_pairs = {('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")}
    if len(evidence) >= 10 and (evidence[0], evidence[-1]) in quote_pairs:
        unquoted = evidence[1:-1]
        if len(unquoted) >= 8 and unquoted in brief:
            return unquoted
    return None


def apply_supported_updates(project, item):
    allowed = {"objective", "prediction_unit", "success_criterion", "compute_budget", "token_budget"}
    applied = []
    brief = project["brief"]
    design_was_empty = not project["design"].get("target")
    columns = {c["name"] for c in (project.get("dataset") or {}).get("columns", [])}
    for suggestion in item.get("updates", []):
        if not isinstance(suggestion, dict):
            continue
        key, val, evidence = suggestion.get("field"), suggestion.get("value", ""), suggestion.get("evidence", "")
        matched = _matched_evidence(evidence, brief)
        if not isinstance(key, str) or not isinstance(val, str) or not val.strip() or len(val) > 2000 or matched is None:
            continue
        # Retain the original proposal in item["updates"]. The applied record
        # contains the exact source substring that passed verification.
        if key in allowed and not project["answers"].get(key):
            project["answers"][key] = val
            applied.append({"field": key, "evidence": matched})
        elif design_was_empty:
            options = {"target": columns, "task": {"classification", "regression"}, "metric": {"accuracy", "balanced_accuracy", "roc_auc", "rmse", "mae"},
                       "split": {"random", "group", "time"}, "group_column": columns, "time_column": columns}
            if key in options and val in options[key]:
                project["design"][key] = val
                applied.append({"field": key, "evidence": matched})
    item["applied"] = applied
    return bool(applied)
