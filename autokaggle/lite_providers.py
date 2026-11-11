"""Model providers for Lite. OpenRouter is the default; DeepSeek is an alternative.

Select with AUTOKAGGLE_LITE_PROVIDER=openrouter or deepseek. The OpenRouter
interview stays the unchanged code in lite.py. This module adds the DeepSeek
interview call and the provider details the evaluator build needs.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
PROVIDERS = {
    "openrouter": {"label": "OpenRouter", "upstream": "https://openrouter.ai/api/v1", "key": "OPENROUTER_API_KEY"},
    "deepseek": {"label": "DeepSeek", "upstream": "https://api.deepseek.com", "key": "DEEPSEEK_API_KEY"},
}
# DeepSeek accepts low, high, and max. Its documentation maps the other names as below.
DEEPSEEK_EFFORT = {"minimal": "low", "low": "low", "medium": "high", "high": "high", "xhigh": "high", "max": "max", "ultra": "max"}


def selected():
    name = os.getenv("AUTOKAGGLE_LITE_PROVIDER", "openrouter").strip().lower()
    if name not in PROVIDERS:
        raise ValueError("AUTOKAGGLE_LITE_PROVIDER must be openrouter or deepseek.")
    return name


def label(name=None):
    return PROVIDERS[name or selected()]["label"]


def key(name=None):
    return os.getenv(PROVIDERS[name or selected()]["key"])


def missing_key(name=None):
    provider = PROVIDERS[name or selected()]
    return f"{provider['label']} is not configured. Add {provider['key']} in the private environment file."


def model(name=None):
    """The interview model for a provider. The evaluator build can override it."""
    if (name or selected()) == "deepseek":
        return os.getenv("AUTOKAGGLE_LITE_DEEPSEEK_MODEL", "deepseek-v4-pro")
    return os.getenv("AUTOKAGGLE_LITE_MODEL", "openai/gpt-6.1-sol")


def reasoning(name, effort):
    """Request fields that set the reasoning level. The application sets these, not the build job."""
    if name == "deepseek":
        if effort in {"none", "off", "disabled"}:
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "enabled"}, "reasoning_effort": DEEPSEEK_EFFORT.get(effort, "high")}
    return {"reasoning": {"effort": effort}}


def agent_model(name, model_id, effort):
    """The coding agent's model entry. DeepSeek needs its reasoning text returned on later tool-call turns."""
    entry = {"name": model_id}
    if name == "deepseek":
        entry.update(tool_call=True, limit={"context": 1000000, "output": 64000})
        if "thinking" in reasoning(name, effort) and reasoning(name, effort)["thinking"]["type"] == "enabled":
            entry.update(reasoning=True, interleaved={"field": "reasoning_content"})
    return entry


def material(lite, state):
    """The interview context. It must stay identical to the context lite.propose sends; a test compares them."""
    current = (state.get("proposal") or {}).get("contract", state["contract"])
    open_decisions = (state.get("proposal") or {}).get("open_decisions", state.get("open_decisions", []))
    return {"messages": state["messages"][-40:], "sources": state["sources"], "accepted_contract": state["contract"],
            "saved_result_summaries": lite.result_context(state), "current_contract_version": lite.version(state["contract"], state["sources"]),
            "current_proposal": current, "open_decisions": open_decisions, "missing": lite.checklist(current, open_decisions),
            "contract_fields": sorted(lite.FIELDS), "field_help": lite.CONTRACT_HELP,
            "field_types": {**{field: {"type": "string"} for field in lite.STRINGS},
                            **{field: {"type": "string", "enum": sorted(values)} for field, values in lite.ENUMS.items()},
                            **{field: {"type": "integer or null" if field == "max_steps" else "integer", "minimum": bounds[0], "maximum": bounds[1]}
                               for field, bounds in lite.INTS.items()},
                            "environment_imports": {"type": "array of Python module names"}, "environment_kwargs": {"type": "object"}}}


def propose_deepseek(lite, state):
    """The Lite interview turn on DeepSeek. It has JSON output but no strict schema, so the schema goes in the prompt.

    lite.parse_proposal applies the same validation as on OpenRouter.
    """
    if not key("deepseek"):
        raise ValueError(missing_key("deepseek"))
    from openai import OpenAI
    system = (open(os.path.join(HERE, "prompts", "lite.md")).read()
              + "\n\nReturn one JSON object and nothing else. It must match this JSON schema exactly, including every required key:\n"
              + json.dumps(lite.model_schema()))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(material(lite, state), ensure_ascii=False)}]
    with OpenAI(api_key=key("deepseek"), base_url=PROVIDERS["deepseek"]["upstream"], timeout=150, max_retries=0) as client:
        response = None
        for _ in range(2):
            response = client.chat.completions.create(model=model("deepseek"), messages=messages, response_format={"type": "json_object"},
                                                      extra_body=reasoning("deepseek", "medium"), max_tokens=16000)
            # DeepSeek documents that JSON output can come back blank. Ask once more before reporting a failure.
            if response.choices and (response.choices[0].message.content or "").strip():
                break
    return lite.parse_proposal(state, response)


def install(lite):
    """Route the interview by provider without editing lite.py, whose bytes are part of every contract version."""
    original = lite.propose
    if getattr(original, "_lite_provider_router", False):
        return

    def propose(state):
        return propose_deepseek(lite, state) if selected() == "deepseek" else original(state)

    propose._lite_provider_router = True
    lite.propose = propose
