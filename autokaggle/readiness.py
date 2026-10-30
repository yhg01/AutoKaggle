"""Evidence-based requirements for a sufficiently defined challenge.

These checks measure the recorded brief. They do not certify scientific truth,
data access, or a successful run. The conversation layer validates evidence
against researcher messages before it stores a requirement assessment.
"""
from __future__ import annotations

import re

from .onboarding_setup import validate_email


DEFINITION = (
    "Within the agreed scope, another research agent can "
    "implement an attempt and interpret its score without inventing scientific assumptions."
)

FIELD_LABELS = {
    "question": "Research problem", "task": "Inputs and outputs",
    "data": "Data or environment", "methodology": "Methodology",
    "deployment": "Deployment and evaluation", "difficulty": "Reference method",
    "evaluation": "Evaluation design", "leakage": "Data exposure",
    "protocol": "Scientific constraints", "competition": "Submission format",
    "submissions": "Daily submissions", "review": "Review",
    "plan": "Budget and schedule", "organizer": "Organizer email",
    "trial": "Baseline verification", "entry": "Participant materials",
    "support": "Support",
}


def _requirement(identifier, label, description, *, allow_not_applicable=False):
    return {"id": identifier, "label": label, "description": description,
            "allow_not_applicable": allow_not_applicable}


REQUIREMENTS = {
    "question": [
        _requirement("scope", "Target system and scope", "Identify the system, population, or instances and the scientific question. State what is inside and outside the task."),
        _requirement("value", "Scientific value", "Explain why answering the question would matter and what current difficulty it addresses."),
        _requirement("success", "Useful progress", "Define an observable success condition or comparison. A general wish to improve performance is insufficient; a functional reference method is not required."),
    ],
    "task": [
        _requirement("inputs", "Input definition", "Specify the fields, units, observation unit, and available context needed for one attempt. For code or optimization, define the problem instance."),
        _requirement("outputs", "Output definition", "Specify what each prediction, response, or candidate represents and its required shape, units, and constraints. The application supplies platform file interfaces."),
        _requirement("metric", "Metric and direction", "Name or define the scoring metric, its direction, and its aggregation across examples. Define any weights, costs, or tolerances that affect the score."),
    ],
    "data": [
        _requirement("source", "Dataset or generation source", "Provide a source link for existing data. Prefer Google Drive with Anyone with the link and Viewer access. For new generated data, specify a reproducible generation procedure and its code or documentation link if one exists. A link does not prove access or import."),
        _requirement("outcomes", "Labels or outcomes", "Define the target labels or observed outcomes, their units, how they are produced, and the observation horizon. For optimization without labels, explicitly explain why labels are not needed.", allow_not_applicable=True),
        _requirement("permission", "Data use permission", "State the permission or license to use the data and to distribute the approved participant inputs. Public link access alone does not establish this permission."),
    ],
    "methodology": [
        _requirement("methods", "Method choices", "State required, allowed, or prohibited methods. An explicit choice to allow any method meets this requirement."),
        _requirement("resources", "External resources", "State whether external data, pretrained models, and external services may be used. An explicit unrestricted policy is acceptable if compatible with execution constraints."),
    ],
    "deployment": [
        _requirement("setting", "Intended use", "State where and how a solution would be used. An offline scientific benchmark is a valid setting."),
        _requirement("information", "Information at decision time", "Specify what the solution can observe at each decision, including time, history, state, and any unavailable future information."),
        _requirement("timing", "Timing and updates", "State the required inference cadence, latency, state changes, and update policy, or explicitly state that these restrictions do not apply to an offline task."),
        _requirement("limits", "Operational limits", "Specify relevant compute, memory, hardware, runtime, and access constraints, or explicitly state which limits the platform may set. Do not make the researcher choose platform versions."),
        _requirement("outcome", "Output to measured outcome", "Explain how the submitted output produces the scored outcome and how that score relates to the intended use. For trading, distinguish forecast error, a backtest, and later market performance; include execution, cost, and risk assumptions when relevant."),
    ],
    "difficulty": [
        _requirement("reference", "Reference method", "Identify the strongest relevant known method and its paper, code, or other source, if a functional reference exists.", allow_not_applicable=True),
        _requirement("reported_result", "Reported result and conditions", "Record the reported score, data, metric, and evaluation conditions. Keep reported results separate from results measured by this application.", allow_not_applicable=True),
        _requirement("reproduction", "Reproduction materials", "Record available code, model assets, dependencies, compute needs, and known differences needed to reproduce the reference. State unavailable material explicitly.", allow_not_applicable=True),
    ],
    "evaluation": [
        _requirement("population", "Evaluation population", "Specify the systems, conditions, instances, or future periods that the evaluation must represent."),
        _requirement("independence", "Independent sampling unit", "Define independent examples and which related examples, groups, or time periods must remain together. Explicitly state when all published instances are evaluated without sampling."),
        _requirement("holdout", "Holdout and feedback policy", "Confirm the scientific train/test and public/private allocation, with a reason for grouping or time order. For future data or optimization, define the applicable time or instance policy; do not invent labels or a random split."),
        _requirement("uncertainty", "Evaluation size and uncertainty", "Specify the evaluation size and how uncertainty or score stability will be assessed. A deterministic, fixed instance task may explicitly state that sampling uncertainty is not applicable.", allow_not_applicable=True),
        _requirement("workflow", "Task-specific evaluation rules", "For fixed prediction, define the test outcome and aggregation. For future data, define source, cutoff, collection window, outcome availability, and corrections. For optimization, define feasibility, objective direction, and numeric tolerances. For sequential inference, define order and permitted state."),
    ],
    "leakage": [
        _requirement("related_samples", "Related examples and duplicates", "Identify duplicates and related examples that could cross evaluation boundaries and state how to prevent this, or explicitly state that none are known after review."),
        _requirement("exposure", "Existing answer exposure", "State whether answers or close proxies are public or otherwise available to participants, and how the evaluation accounts for that exposure."),
        _requirement("preprocessing", "Preprocessing boundaries", "Specify how preprocessing, feature selection, and normalization avoid using held-out outcomes or future information. Explicitly state when no learned preprocessing is used."),
    ],
    "protocol": [
        _requirement("restrictions", "Scientific restrictions", "State any remaining scientific or experimental constraints. An explicit statement that there are no additional constraints is sufficient. Application-owned interfaces and versions are separate."),
    ],
    "competition": [
        _requirement("choice", "Competition type", "Choose prediction submissions or code submissions through the validated organizer setting."),
    ],
    "submissions": [
        _requirement("allowance", "Confirmed daily allowance", "Confirm five submissions per team per UTC day or choose another positive daily limit through the validated organizer setting."),
    ],
    "review": [
        _requirement("owner", "Scientific review owner", "Name the person or role responsible for reviewing scientific assumptions. The organizer can take this responsibility."),
        _requirement("status", "Review plan or status", "State whether scientific review is pending or complete and how remaining decisions will be checked. A pending review with an owner and plan is sufficient to define the challenge."),
    ],
    "plan": [
        _requirement("compute_budget", "Compute budget in dollars", "Give a numeric dollar estimate or range for compute for a credible attempt. Zero is valid when no paid compute is needed. Unknown is still an open requirement."),
        _requirement("token_budget", "Model-token budget in dollars", "Give a separate numeric dollar estimate or range for model tokens for a credible attempt. Zero is valid when no paid model calls are needed. Unknown is still an open requirement."),
        _requirement("ownership", "Budget limits and owner", "State who owns the compute and token budget decisions and any hard limits. An explicit decision that no further financial limit applies is acceptable."),
        _requirement("schedule", "Schedule", "State relevant dates or attempt duration, or explicitly state that the challenge has no schedule constraint."),
    ],
    "organizer": [
        _requirement("contact", "Validated private email", "Supply a valid private organizer email through the validated organizer setting."),
    ],
    "trial": [
        _requirement("execution", "Measured reference run", "Application-owned optional reference reproduction. A human statement is not execution evidence. Required evaluator checks remain separate from scientific definition."),
    ],
    "entry": [
        _requirement("participants", "Intended participants", "Specify who should be able to enter, including any access or eligibility restrictions. An open invitation is an explicit choice."),
        _requirement("prerequisites", "Required knowledge", "State the domain knowledge or experience expected from participants, or explicitly state that none is required beyond the supplied materials."),
    ],
    "support": [
        _requirement("contact", "Participant support", "Specify the contact or support process for task questions, or explicitly state that no additional support is planned."),
        _requirement("rules", "Deadlines and incentives", "State applicable participant deadlines and incentives, or explicitly state that there are none. Keep this consistent with the schedule."),
        _requirement("results", "Results review", "State who will interpret the results and how results and remaining issues will be returned for review."),
    ],
}

OPTIONAL_FIELDS = frozenset({"difficulty", "trial"})
REQUIRED_FIELDS = tuple(field for field in REQUIREMENTS if field not in OPTIONAL_FIELDS)
SERVER_FIELDS = frozenset({"organizer", "competition", "submissions"})
MAX_BYPASS_REASON = 2000
SCOPE_MODES = frozenset({"confirmed", "delegated", "exception"})
DELEGATION_POLICIES = {
    ("methodology", "methods"): "The research agent may choose an implementation method within the recorded scientific objective, data permissions, submission contract, and method restrictions. It may not change those decisions.",
    ("deployment", "limits"): "Use the fixed platform code-runner ceiling: 1 CPU, 512 MiB memory, 90 CPU seconds, 100 program seconds, 120 job seconds, no GPU, and no network access. This does not select a scientific budget or claim that a run passed.",
    ("leakage", "preprocessing"): "Choose preprocessing using training data only. Fit normalization, feature selection, and tuning only within the training partition. Do not use validation or final outcomes, future information, or hidden membership.",
}


def can_accept_scope(field):
    return field in REQUIREMENTS and field not in SERVER_FIELDS and field != "trial"


def can_delegate(field, requirement_id):
    return (field, requirement_id) in DELEGATION_POLICIES


def scope_resolution(field, item, requirement_id):
    """Read an explicit organizer resolution separately from scientific facts."""
    if not can_accept_scope(field) or not isinstance(item, dict):
        return None
    scope = item.get("scope")
    if not isinstance(scope, dict) or not _text(scope.get("summary")):
        return None
    records = scope.get("resolutions", [])
    if not isinstance(records, list):
        return None
    for record in records:
        if not isinstance(record, dict) or record.get("requirement_id") != requirement_id or record.get("stale"):
            continue
        mode, detail = record.get("mode"), record.get("detail")
        if mode not in SCOPE_MODES or not _text(detail) or len(detail) > 2000:
            continue
        if mode == "delegated" and (not can_delegate(field, requirement_id)
                                    or record.get("policy") != DELEGATION_POLICIES[(field, requirement_id)]):
            continue
        if mode == "confirmed" and (_unknown_only(detail) or (field == "plan" and requirement_id in {"compute_budget", "token_budget"}
                                                              and not _budget_amount({"value": detail}))):
            continue
        return record
    return None


def can_bypass(field, requirement_id):
    """Only organizer-owned definition criteria can receive a manual exception."""
    return (field in REQUIRED_FIELDS and field not in SERVER_FIELDS
            and any(criterion["id"] == requirement_id for criterion in REQUIREMENTS[field]))


def bypass_record(field, item, requirement_id):
    """Read a separate manual decision; model assessments cannot grant bypasses."""
    if not can_bypass(field, requirement_id) or not isinstance(item, dict):
        return None
    records = item.get("bypasses", {})
    record = records.get(requirement_id) if isinstance(records, dict) else None
    if (not isinstance(record, dict) or not _text(record.get("reason"))
            or len(record["reason"].strip()) > MAX_BYPASS_REASON):
        return None
    return {key: record[key] for key in ("reason", "created_at", "updated_at") if key in record}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _has_evidence(evidence):
    """Require a nonempty source excerpt; source matching belongs to the caller."""
    if not isinstance(evidence, list):
        return False
    for entry in evidence:
        if _text(entry):
            return True
        if isinstance(entry, dict) and isinstance(entry.get("quotes"), list):
            if any(_text(quote) for quote in entry["quotes"]):
                return True
    return False


def _unknown_only(value):
    normalized = re.sub(r"[.!?,;:'\"\s]+", " ", value.lower()).strip()
    return normalized in {
        "unknown", "not known", "not yet known", "not sure", "unsure", "tbd",
        "to be determined", "to be decided", "unavailable", "not available",
        "i don t know", "we don t know", "unknown estimate", "unknown estimates",
    }


def _budget_amount(record):
    texts = [record.get("value", "")]
    for entry in record.get("evidence", []):
        if isinstance(entry, str):
            texts.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("quotes"), list):
            texts.extend(quote for quote in entry["quotes"] if isinstance(quote, str))
    amount = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    currency_before = r"(?<![-\w])(?:US\$|\$|USD\s*)\s*" + amount
    currency_after = r"(?<![-\w.])" + amount + r"\s*(?:USD\b|(?:US\s+)?dollars?\b)"
    return any(re.search(currency_before + "|" + currency_after, text, re.I) for text in texts)


def _server_complete(field, item):
    """Accept only the values produced by validated organizer settings."""
    if item.get("status") != "answered" or not _text(item.get("value")):
        return False
    value = item["value"].strip()
    if field == "organizer":
        try:
            return bool(validate_email(value))
        except ValueError:
            return False
    if field == "competition":
        return value in {
            "Prediction competition: participants submit predictions for supplied test inputs.",
            "Code competition: submitted code runs against hidden test inputs.",
        }
    if field == "submissions":
        match = re.fullmatch(r"([1-9][0-9]{0,3}) submissions per day \(confirmed\)\.", value)
        return bool(match and int(match[1]) <= 1000)
    return False


def criterion_result(field, item, criterion):
    """Return completion and a safe gap description for one known requirement."""
    if bypass_record(field, item, criterion["id"]):
        return True, ""
    if scope_resolution(field, item, criterion["id"]):
        return True, ""
    if field in SERVER_FIELDS:
        complete = _server_complete(field, item)
        return complete, "" if complete else criterion["description"]
    if field == "trial":
        # Execution is reported by the workflow, never by interview evidence.
        return False, "The application reports reference execution separately. This optional check does not block scientific definition."
    requirements = item.get("requirements")
    record = requirements.get(criterion["id"], {}) if isinstance(requirements, dict) else {}
    if not isinstance(record, dict):
        record = {}
    status = record.get("status", "missing")
    if status == "recorded":
        if _text(record.get("value")) and _has_evidence(record.get("evidence")):
            if _unknown_only(record["value"]):
                return False, "The answer is unknown. This required decision remains open."
            if field == "plan" and criterion["id"] in {"compute_budget", "token_budget"} and not _budget_amount(record):
                return False, "Provide a numeric dollar estimate or range. Zero dollars is valid when no paid use is needed."
            return True, ""
        return False, "A recorded answer needs a value and supporting evidence."
    if status == "not_applicable":
        if not criterion["allow_not_applicable"]:
            return False, "This requirement needs an explicit decision. It cannot be omitted."
        if _text(record.get("reason")) and _has_evidence(record.get("evidence")):
            if _unknown_only(record["reason"]):
                return False, "An unknown answer does not establish that this requirement is not applicable."
            return True, ""
        return False, "Explain why this requirement does not apply and provide supporting evidence."
    reason = record.get("reason")
    if _text(reason):
        return False, reason.strip()
    if status == "deferred":
        return False, "The answer is deferred. This required decision remains open."
    return False, criterion["description"]


def item_understanding(field, item):
    """Count complete requirements; never infer completion from an answer flag."""
    criteria = REQUIREMENTS.get(field, [])
    item = item if isinstance(item, dict) else {}
    completed = sum(criterion_result(field, item, criterion)[0] for criterion in criteria)
    bypassed = sum(bool(bypass_record(field, item, criterion["id"])) for criterion in criteria)
    resolutions = [scope_resolution(field, item, criterion["id"]) for criterion in criteria]
    counts = {mode: sum(bool(record and record["mode"] == mode) for record in resolutions) for mode in SCOPE_MODES}
    total = len(criteria)
    required = field in REQUIRED_FIELDS
    score = round(100 * completed / total) if total else 0
    if field == "trial":
        score = None
        label = "Optional system check"
        detail = "Reference reproduction is optional. The workflow reports measured execution separately."
    else:
        label = "Requirements met" if total and completed == total else "Details missing" if completed else "Not yet defined"
        detail = f"{completed} of {total} requirements met."
        if bypassed:
            label = "Resolved with bypass" if completed == total else "Details missing; bypass recorded"
            detail = f"{completed} of {total} requirements resolved, including {bypassed} manual bypass{'es' if bypassed != 1 else ''}."
        if any(counts.values()):
            label = "Scope accepted" if completed == total else "Scope partly accepted"
            detail = f"{completed} of {total} requirements resolved. Organizer decisions: {counts['confirmed']} confirmed, {counts['delegated']} delegated, {counts['exception']} exception{'s' if counts['exception'] != 1 else ''}."
        if not completed and _text(item.get("value")) and not item.get("requirements") and field not in SERVER_FIELDS:
            label = "Assessment pending"
            detail += " Saved answers will be checked against these requirements on the next reply."
        if not required:
            detail += " This reference is optional and does not block the challenge."
    return {"score": score, "label": label, "detail": detail,
            "completed": completed, "total": total, "required": required, "bypassed": bypassed, **counts}


def assess(state):
    """Return required scientific gaps without exposing the recorded answers."""
    items = state.get("items", {}) if isinstance(state, dict) else {}
    if not isinstance(items, dict):
        items = {}
    blockers, bypasses, scope_decisions, completed, total = [], [], [], 0, 0
    for field in REQUIRED_FIELDS:
        item = items.get(field, {})
        item = item if isinstance(item, dict) else {}
        for criterion in REQUIREMENTS[field]:
            total += 1
            complete, reason = criterion_result(field, item, criterion)
            completed += int(complete)
            bypass = bypass_record(field, item, criterion["id"])
            if bypass:
                bypasses.append({"field": field, "label": FIELD_LABELS[field],
                                 "requirement_id": criterion["id"],
                                 "requirement_label": criterion["label"], **bypass})
            resolution = scope_resolution(field, item, criterion["id"])
            if resolution:
                scope_decisions.append({"field": field, "label": FIELD_LABELS[field],
                                        "requirement_id": criterion["id"], "requirement_label": criterion["label"],
                                        **{key: resolution[key] for key in ("mode", "detail", "policy") if key in resolution}})
            if not complete:
                blockers.append({"field": field, "label": FIELD_LABELS[field],
                                 "requirement_id": criterion["id"],
                                 "requirement_label": criterion["label"], "reason": reason})
    baseline = item_understanding("difficulty", items.get("difficulty", {}))
    if isinstance(state, dict) and state.get("_unprocessed"):
        total += 1
        blockers.append({"field": "question", "label": "Saved researcher messages", "requirement_id": "pending_messages",
                         "requirement_label": "Assess saved answers and corrections",
                         "reason": "A researcher message has not been assessed. Retry it or resolve it before treating the challenge as defined."})
    reference_records = items.get("difficulty", {}).get("requirements", {}) if isinstance(items.get("difficulty"), dict) else {}
    unavailable = bool(reference_records) and all(reference_records.get(c["id"], {}).get("status") == "not_applicable" for c in REQUIREMENTS["difficulty"])
    optional = {"status": "not_available" if unavailable else "recorded" if baseline["completed"] == baseline["total"] else
               "partial" if baseline["completed"] else "not_provided",
               "detail": "A functional reference baseline is optional. Its absence does not block the challenge. Measured evaluator checks remain separate."}
    return {"definition": DEFINITION, "ready": not blockers, "completed": completed,
            "total": total, "blockers": blockers, "optional_baseline": optional,
            "bypassed": len(bypasses), "bypasses": bypasses, "scope_decisions": scope_decisions,
            **{mode: sum(record["mode"] == mode for record in scope_decisions) for mode in SCOPE_MODES}}
