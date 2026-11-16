"""Interview context and evidence handling. These do not change contract hashes."""
from __future__ import annotations

import copy
import json
import re


def context(state):
    proposal = state.get("proposal") or {}
    return {
        "accepted_evidence": state.get("accepted_evidence", {}),
        "proposed_evidence": proposal.get("evidence", {}),
        "workflow_responsibilities": {
            "researcher_now": "Define the scientific claim, required metrics and outputs, artifact interface, data rights, protocol, and resource bounds. Approve proposed choices.",
            "agent_now": "Read supplied sources. Propose supported values with exact evidence. Identify one missing scientific decision. Retain all required secondary metrics and outputs.",
            "coding_agent_after_acceptance": "Implement the adapter, dependency lock, realistic fixtures, invalid-input tests, and contract coverage. Use the pinned official scorer when suitable. Test in isolation and repair software defects.",
            "service_after_checks": "Create the evaluator repository and release URL, then record its commit. These generated identifiers are not inputs to the scientific interview.",
            "researcher_at_execution": "Supply permitted local data and the experiment artifact. The local runner records their digests, the evaluator release, and measured outputs.",
            "release_evidence": "Software checks on synthetic data do not establish validation on declared research data. That later validation and human approval remain separate requirements.",
        },
        "package_interface": {
            "adapter": "evaluate(seed, manifest, contract)",
            "artifact": "artifact_path and artifact_sha256; a local file or directory",
            "reference": "For adapters with reference data: reference_path, reference_sha256, evaluation_mode (synthetic or research). Licensed files can stay local; a public download URL is not required.",
            "outputs": "The runner supplies output_directory. Save required outputs there and return their relative paths in outputs. The runner records output_files with sizes and hashes.",
            "result": "seed, status, score, steps; optional elapsed_seconds and end_reason. Quality-enabled evaluators also return metrics and reference (mode, identity, sha256). Required metrics and outputs are defined by quality.json.",
            "large_assets": "Keep large data and model files outside Git and chat. Record the schema, access procedure, identity, size, and checksums. Stream or process them in bounded batches within the declared resources.",
        },
    }


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _exact_excerpt(excerpt, pool):
    """Recover line-wrap differences only. Never match paraphrases or alter numbers."""
    if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 2000:
        return excerpt
    for text in pool:
        if excerpt in text:
            return excerpt
    pattern = r"\s+".join(re.escape(word) for word in excerpt.split())
    for text in pool:
        match = re.search(pattern, text)
        if match and len(match[0]) <= 2000:
            return match[0]
    return excerpt


def parse(lite, state, response):
    """Keep evidence exact and retain provenance for unchanged accepted decisions."""
    prepared = response
    try:
        data = json.loads(response.choices[0].message.content)
        updates = data.get("updates")
        if isinstance(updates, list):
            pools = {
                "researcher": [m["content"] for m in state.get("messages", []) if m.get("role") == "user"],
                "source": list(_strings(state.get("sources", []))),
            }
            for update in updates:
                if isinstance(update, dict) and isinstance(update.get("basis"), str) and update["basis"] in pools:
                    update["evidence"] = _exact_excerpt(update.get("evidence"), pools[update["basis"]])
            prepared = copy.deepcopy(response)
            prepared.choices[0].message.content = json.dumps(data)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        pass  # The contract parser reports malformed responses and keeps saved facts safe.
    result = lite.parse_proposal(state, prepared)
    prior = state.get("proposal") or {}
    for contract, evidence in ((state.get("contract", {}), state.get("accepted_evidence", {})),
                               (prior.get("contract", {}), prior.get("evidence", {}))):
        for field, entry in evidence.items():
            if field not in result.get("contract", {}) or result["contract"][field] != contract.get(field):
                continue
            recorded = result.setdefault("evidence", {}).get(field)
            if recorded is None or (recorded.get("basis") == "suggestion" and entry.get("basis") in {"researcher", "source"}):
                result["evidence"][field] = copy.deepcopy(entry)
    return result
