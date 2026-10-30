"""Bounded, evidence-backed conversation and deterministic challenge README."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import uuid

from . import advisor, onboarding_setup, readiness

ITEMS = [
    ("question", "Research problem", "Problem", "What scientific problem should the research solve?", "Scientific question, practical value, and the outcome that would count as useful progress."),
    ("task", "Inputs and outputs", "Problem", "What should a solution produce from the available inputs?", "Inputs, required outputs, a useful metric, and the intended scientific outcome."),
    ("data", "Data or environment", "Problem", "Which dataset or simulation setup provides the inputs and, if needed, their labels?", "Dataset or generator link, sources or problem instances, labels if needed, permission, and related samples or time ordering. Request a Google Drive link with Anyone with the link and Viewer access as the standard option. Other source links are accepted. Also offer CSV upload up to 200 MB using Data & checks at the bottom left. Do not require labels for optimization."),
    ("methodology", "Methodology", "Method and deployment", "Should researchers use a particular method, or can they choose the approach?", "Required, allowed, or prohibited methods. Keep method choice distinct from the submitted artifact. A neural network is a method; a prediction file is an artifact."),
    ("deployment", "Deployment and evaluation", "Method and deployment", "Where would the solution run, and what information would it have when it makes a decision?", "Deployment setting, information available at decision time, state, timing, update and resource constraints, and how outputs produce the measured outcome. For trading, distinguish forecast error, backtest returns, and later market performance; define which determines success."),
    ("difficulty", "Reference method", "Reference baseline", "What is the strongest existing method you would compare against, and what result does it report?", "Relevant reference method, paper or code if known, reported score and evaluation conditions, and known requirements to run it. State unavailable or unknown materials explicitly. Reported results are not measured results from this system."),
    ("evaluation", "Evaluation design", "Problem", "What situations or future periods must the evaluation represent?", "Scientific split design, independent samples, test size, and uncertainty. Future-data tasks need a source, cutoff, collection window, outcome availability, and correction policy; historical replay is not a live future-data run. Optimization needs feasibility rules, objective direction, and numeric tolerances."),
    ("leakage", "Data exposure", "Problem", "Could related samples or answers already available elsewhere reveal the test answers?", "Duplicates, related samples, preprocessing, answer proxies, and public exposure."),
    ("protocol", "Scientific constraints", "Method and deployment", "Are there scientific restrictions beyond the method and deployment limits already discussed?", "Scientific restrictions and any conflict with the available platform. Do not ask the scientist to define platform interfaces, environment versions, or score feedback."),
    ("competition", "Submission format", "Organizer settings", "Should participants submit a prediction file, or code that runs on hidden inputs?", "Explicit choice of prediction or code competition. This is the submitted artifact, not a restriction to a model family."),
    ("submissions", "Daily submissions", "Organizer settings", "Do you confirm five submissions per team per day, or want a different daily limit?", "Confirm or change the default of five submissions per day."),
    ("review", "Review", "Organizer settings", "Who can review the scientific assumptions in the draft?", "Independent reviewer and the state of the review."),
    ("plan", "Budget and schedule", "Organizer settings", "What compute and model-token budgets would give this problem a credible attempt?", "Separate dollar estimates or ranges for compute and model tokens, hard limits, owners, and relevant dates. Unknown estimates are acceptable."),
    ("organizer", "Organizer email", "Organizer settings", "Which email address should we use for your private draft review?", "A valid private organizer email for draft review."),
    ("trial", "Baseline verification", "Reference baseline", "", "Application-owned check: run the reference through the participant interface and actual evaluator on development data. Record source, version, environment, cost, measured result, and differences from the reported result. A researcher's assertion is not execution evidence. Keep final holdout feedback protected."),
    ("entry", "Participant materials", "Organizer settings", "Who should be able to use this challenge?", "Intended participants and domain prerequisites. The application prepares instructions, starter code, and examples."),
    ("support", "Support", "Organizer settings", "Are there deadlines or support arrangements the participants should know?", "Rules, deadlines, incentives, help, communication, and results analysis."),
]
BY_ID = {item[0]: item for item in ITEMS}
PILLARS = list(dict.fromkeys(item[2] for item in ITEMS))
INTERVIEW_STAGES = [
    ("problem", "Problem", ("question", "task", "data", "evaluation", "leakage")),
    ("approach", "Method and deployment", ("methodology", "deployment", "protocol")),
    ("baseline", "Reference baseline", ("difficulty",)),
]
CORE_FIELDS = {"question", "task", "data", "methodology", "deployment", "evaluation", "leakage", "protocol", "plan"}
AGENT_OWNED_FIELDS = {"trial"}
QUESTION_ORDER = ("question", "task", "data", "methodology", "deployment", "difficulty", "evaluation", "leakage", "plan", "protocol", "competition", "submissions", "organizer", "review", "entry", "support")
PARTIAL_QUESTIONS = {
    "question": "What improvement would count as useful progress for this research?",
    "task": "What should each submitted result contain?",
    "data": "What permission applies to the data you described?",
    "methodology": "Which methods must participants use or avoid?",
    "deployment": "What information is available when the solution makes each decision?",
    "difficulty": "What result does the reference method report under comparable conditions?",
    "evaluation": "Which conditions must the evaluation represent?",
    "leakage": "Which related samples must stay together to prevent exposure of test answers?",
    "protocol": "Which scientific constraint should the challenge enforce?",
    "plan": "What compute and model-token costs would give one attempt a credible chance?",
    "review": "Who can review the remaining scientific assumptions?",
    "entry": "What domain knowledge should participants need?",
    "support": "Which deadline should participants work toward?",
}
MAX_FOLLOWUPS = 8
MAX_CALLS = 12
MAX_REVISION_ROUNDS = 20


class ModelResponseError(ValueError):
    """A fixed validation message, never raw provider or researcher content."""

    def __init__(self, message):
        super().__init__(message)
        self.code = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_")
        self.feedback = message + ". Return a complete replacement JSON response. Use one update per field and one assessment per field/id pair. Update evidence must be copied exactly from current_message. Requirement evidence must be copied exactly from permitted researcher sources. Correction supersedes spans must match the prior value or active confirmed scope detail exactly. Keep supported changes and preserve unrelated facts."


def _record_response_issue(state, kind, code, attempt):
    # Only application-owned identifiers cross the diagnostics boundary.
    issues = state.setdefault("_response_diagnostics", [])
    issues.append({"kind": kind, "code": code, "attempt": attempt})
    del issues[:-20]


def _validated_response(project, kind, context, reserve, validate):
    """Repair one invalid model response without applying partial evidence."""
    state = ensure_conversation(project)
    request_context = copy.deepcopy(context)
    previous = state.get("_last_response_failure")
    if previous and previous.get("kind") == kind:
        request_context["response_repair"] = copy.deepcopy(previous)
    for attempt in (1, 2):
        try:
            parsed = _provider(project, kind, request_context, reserve)
            result = validate(parsed)
        except ModelResponseError as exc:
            feedback = {"kind": kind, "code": exc.code, "instruction": exc.feedback}
            state["_last_response_failure"] = feedback
            _record_response_issue(state, kind, exc.code, attempt)
            if attempt == 2 or state.get("_automatic_repair_used") or _call_count(project) >= MAX_CALLS:
                raise
            state["_automatic_repair_used"] = True
            request_context["response_repair"] = feedback
        else:
            state.pop("_last_response_failure", None)
            return result


REVISION_MESSAGE = (
    "What do you want to see changed? Is the issue in the problem definition, "
    "method and deployment, or our attempt to reproduce the baseline?"
)
INITIAL_MESSAGE = (
    "First, let's define the problem and the research question we want to answer.\n\n"
    "In a few sentences, describe:\n"
    "- The situation or system you are studying and the current difficulty.\n"
    "- What you want to predict, explain, improve, or optimize.\n"
    "- Why the answer matters and what a useful result would look like.\n\n"
    "If you have relevant data, papers, an example, or anything that you think can help explain your intuition, mention it too. "
    "I will ask targeted questions to scope out the question in greater detail"
)
PREVIOUS_INITIAL_MESSAGES = {
    (
        "First, let's define the problem and the research question we want to answer.\n\n"
        "In a few sentences, describe:\n"
        "- The situation or system you are studying and the current difficulty.\n"
        "- What you want to predict, explain, improve, or optimize.\n"
        "- Why the answer matters and what a useful result would look like.\n\n"
        "If you have relevant data, papers, or an example, mention them too. "
        "A rough description is enough. I'll help turn it into a clear, testable research question."
    ),
    "I will help define the problem, how a solution would be used, and the reference method we should test. What scientific problem would you like the research to solve?",
    "Describe your research question, any data you have, what success would mean, and any known constraints. Share what you know; unknowns are fine.",
}
DEFAULT_TITLES = {None, "", "Untitled challenge", "New challenge"}
DATA_SOURCE_GUIDANCE = ('Please share a link. Our standard option is a Google Drive link set to '
                        '"Anyone with the link" with Viewer access. A direct dataset or repository URL also works.')
CSV_UPLOAD_GUIDANCE = ('If your data is a CSV file up to 200 MB, you can upload it using '
                       'Data & checks at the bottom left.')
DATA_LINK_GUIDANCE = DATA_SOURCE_GUIDANCE + " " + CSV_UPLOAD_GUIDANCE


def _data_link_question(state, text, requirement_id=None):
    """Ask for a source link without repeatedly requesting a supplied source."""
    if requirement_id not in {None, "source"}:
        return text
    item = state["items"]["data"]
    text = text.replace("Use a link instead of uploading the full dataset.", "").strip()
    if re.search(r"\b(?:upload|attach)\b", text, re.I) and "csv" not in text.lower():
        text = BY_ID["data"][3]
    if (item["status"] == "deferred" or item.get("requirements", {}).get("source", {}).get("status") == "deferred"
            or readiness.bypass_record("data", item, "source") or readiness.scope_resolution("data", item, "source")
            or re.search(r"https?://\S+", item.get("value", ""), re.I)):
        return text
    normalized = text.lower()
    if not all(part in normalized for part in ("google drive", "anyone with the link", "viewer")):
        text = text.rstrip() + " " + DATA_SOURCE_GUIDANCE
    if not all(part in normalized for part in ("csv", "200 mb", "data & checks", "bottom left")):
        text = text.rstrip() + " " + CSV_UPLOAD_GUIDANCE
    return text


def _message(state, role, content):
    state["messages"].append({"role": role, "content": content, "id": str(uuid.uuid4())})


def ensure_conversation(project):
    if not isinstance(project.get("conversation"), dict):
        state = {"messages": [], "items": {key: {"status": "missing", "value": "", "gap": gap, "evidence": []} for key, _, _, _, gap in ITEMS},
                 "current_question": None, "readme": None, "phase": "initial", "status": "idle", "error": None, "can_retry": False,
                 "followups": 0, "_asked": [], "_requests": {}, "_pending": None, "_inflight": False, "_history": [], "_draft_meta": None, "_unprocessed": []}
        _message(state, "assistant", INITIAL_MESSAGE)
        project["conversation"] = state
    state = project["conversation"]
    # Refresh an untouched opening without rewriting a started interview.
    messages = state.get("messages", [])
    if (state.get("phase") == "initial" and len(messages) == 1
            and messages[0].get("role") == "assistant"
            and messages[0].get("content") in PREVIOUS_INITIAL_MESSAGES
            and not state.get("current_question") and not state.get("readme")
            and not state.get("_pending") and not state.get("_inflight")):
        messages[0]["content"] = INITIAL_MESSAGE
    added = False
    for key, _, _, _, gap in ITEMS:
        if key not in state["items"]:
            state["items"][key] = {"status": "missing", "value": "", "gap": gap, "evidence": []}
            added = True
    state.setdefault("_unprocessed", [])
    state.setdefault("_history", [])
    state.setdefault("_draft_meta", None)
    state.setdefault("_revision_rounds", [])
    state.setdefault("_interview_round", 1)
    state.setdefault("_interview_call_start", 0)
    state.setdefault("_asked_questions", [])
    state.setdefault("_bypass_audit", [])
    state.setdefault("_scope_audit", [])
    state.setdefault("scope_checkpoint", None)
    if "_criterion_asks" not in state:
        state["_criterion_asks"] = {}
        # Legacy questions had only a field. Count them conservatively against
        # the first unresolved criterion; changing rounds must not reset them.
        for field in set(state.get("_asked", [])):
            if field not in readiness.REQUIREMENTS:
                continue
            gaps = [c for c in readiness.REQUIREMENTS[field] if not readiness.criterion_result(field, state["items"][field], c)[0]]
            if gaps:
                state["_criterion_asks"][field + "." + gaps[0]["id"]] = min(2, state["_asked"].count(field))
        active = state.get("current_question")
        if active and active.get("field") in readiness.REQUIREMENTS:
            field = active["field"]
            gaps = [c for c in readiness.REQUIREMENTS[field] if not readiness.criterion_result(field, state["items"][field], c)[0]]
            if gaps:
                active.setdefault("requirement_id", gaps[0]["id"])
                active.setdefault("why", gaps[0]["description"])
                token = field + "." + active["requirement_id"]
                state["_criterion_asks"][token] = max(1, state["_criterion_asks"].get(token, 0))
    if not state.get("_setup_privacy_migrated"):
        for message in state["messages"]:
            if message.get("role") == "user":
                onboarding_setup.remember_private_mentions(project, message.get("content", ""))
        state["_setup_privacy_migrated"] = True
    # Refresh only the current unanswered data prompt. Preserve past exchanges,
    # message identities, retry state, and the number of questions already asked.
    active = state.get("current_question")
    if (active and active["field"] == "data" and active.get("requirement_id") in {None, "source"} and state["status"] == "idle"
            and not state.get("_pending") and not state.get("_inflight") and messages
            and messages[-1].get("role") == "assistant" and messages[-1].get("content") == active["text"]):
        previous_question = re.sub(r"\W+", " ", active["text"].lower()).strip()
        active["text"] = _data_link_question(state, active["text"], active.get("requirement_id"))
        messages[-1]["content"] = active["text"]
        refreshed_question = re.sub(r"\W+", " ", active["text"].lower()).strip()
        if refreshed_question != previous_question:
            histories = [state["_asked_questions"]]
            if _revision(state):
                histories.append(_revision(state)["asked_questions"])
            for history in histories:
                history[:] = [refreshed_question if question == previous_question else question for question in history]
    old_readme = state.get("readme")
    onboarding_setup.sync_checklist(project, state)
    # A previous twelve-item draft remains available, with the new open items.
    # The recursive render sees the already-migrated checklist.
    if added and old_readme:
        state["readme"] = _render(project)
    elif old_readme:
        state["readme"] = onboarding_setup.redact_private(project, old_readme)
    return state


def conversation_view(project):
    state = ensure_conversation(project)
    view = {key: copy.deepcopy(state[key]) for key in ("messages", "current_question", "scope_checkpoint", "readme", "phase", "status", "error", "can_retry", "followups")}
    active = state.get("current_question")
    active_field = active["field"] if active else "question" if state["phase"] == "initial" else None
    view["checklist"] = [{"id": key, "label": label, "pillar": pillar,
                          **{name: state["items"][key][name] for name in ("status", "value", "gap")},
                          "owner": "agent" if key in AGENT_OWNED_FIELDS else "researcher",
                          "active": key == active_field and key not in AGENT_OWNED_FIELDS,
                          "required": key in readiness.REQUIRED_FIELDS,
                          "scope": copy.deepcopy(state["items"][key].get("scope")),
                          "can_accept_scope": readiness.can_accept_scope(key) and state["status"] == "idle" and not any(state.get(name) for name in ("_pending", "_inflight", "_unprocessed")),
                          "requirements": _requirement_view(key, state["items"][key]),
                          "understanding": _item_understanding(key, state["items"][key])}
                         for key, label, pillar, _, _ in ITEMS]
    by_id = {item["id"]: item for item in view["checklist"]}
    view["setup"] = onboarding_setup.get(project)
    view["readiness"] = readiness.assess(state)
    stages = []
    for stage_id, label, fields in INTERVIEW_STAGES:
        statuses = [state["items"][field]["status"] for field in fields]
        status = ("answered" if all(value == "answered" for value in statuses) else
                  "deferred" if all(value in {"answered", "deferred"} for value in statuses) else
                  "partial" if any(value != "missing" for value in statuses) else "missing")
        completed = sum(by_id[field]["understanding"]["completed"] for field in fields)
        bypassed = sum(by_id[field]["understanding"]["bypassed"] for field in fields)
        resolution_counts = {mode: sum(by_id[field]["understanding"][mode] for field in fields) for mode in readiness.SCOPE_MODES}
        total = sum(by_id[field]["understanding"]["total"] for field in fields)
        score = round(100 * completed / total) if total else 0
        stages.append({"id": stage_id, "label": label, "status": status,
                       "required": stage_id != "baseline",
                       "answered": statuses.count("answered"), "total": len(fields), "fields": list(fields),
                       "understanding": {"score": score, "label": "Resolved with bypass" if score == 100 and bypassed else _understanding_label(score),
                                         "completed": completed, "total": total, "required": stage_id != "baseline",
                                         "bypassed": bypassed,
                                         **resolution_counts,
                                         "detail": "Resolved requirements include evidence and explicit organizer scope decisions. Scientific claims still need review."}})
    view["interview"] = {"stages": stages,
        "current_stage": next((stage_id for stage_id, _, fields in INTERVIEW_STAGES if active and active["field"] in fields), "problem" if state["phase"] == "initial" else None),
        "next_question": active["text"] if active else INITIAL_MESSAGE if state["phase"] == "initial" else None,
        "can_draft": state["status"] != "working",
        "can_continue": bool(state.get("readme") and state["phase"] == "draft" and not state.get("current_question")
                             and not _revision(state) and state["status"] == "idle"
                             and not state.get("_pending") and not state.get("_inflight")
                             and not view["readiness"]["ready"] and state["_interview_round"] < MAX_REVISION_ROUNDS),
        "round": state["_interview_round"], "followups_limit": MAX_FOLLOWUPS, "model_call_limit": MAX_CALLS,
        "understanding_note": "Counts show recorded facts and explicit organizer scope decisions. Confirmed, delegated, exception, and bypass decisions have separate labels. These counts do not certify scientific truth or completed execution. The reference baseline is optional.",
        "agent_checks": ["Prepare the submission contract and research package.",
                         "Test the evaluator and submission process. If a reference method is available, report its reproduction separately.",
                         "Check data exposure and return unresolved issues for organizer review."]}
    revision = _revision(state)
    view["review"] = {
        "mode": "revision" if revision else "interview", "round": revision["number"] if revision else 0,
        "status": revision["status"] if revision else "not_started",
        "can_start": bool(state.get("readme") and state["status"] == "idle"
                          and len(state["_revision_rounds"]) < MAX_REVISION_ROUNDS
                          and (not revision or revision["status"] == "draft_ready")),
        "prompt": REVISION_MESSAGE,
        "previous_version": revision["previous"]["workflow"].get("version") if revision else None,
        "requested_changes": copy.deepcopy(revision["requested_changes"]) if revision else [],
        "clarified_changes": copy.deepcopy(revision["clarified_changes"]) if revision else [],
        "changed_fields": list(revision["changed_fields"]) if revision else [],
        "followups": revision["followups"] if revision else 0, "followups_limit": MAX_FOLLOWUPS,
        "model_calls": revision["model_calls"] if revision else 0, "model_call_limit": MAX_CALLS,
    }
    return view


def _revision(state):
    rounds = state.get("_revision_rounds") or []
    return rounds[-1] if rounds else None


def _call_count(project):
    state = project.get("conversation") or {}
    revision = _revision(state)
    return revision["model_calls"] if revision else project.get("_model_calls", 0) - state.get("_interview_call_start", 0)


def _workflow_context(project):
    """Use saved development results only. Do not load private evaluator files."""
    workflow = project.get("workflow") or {}
    first = workflow.get("first_result") or {}
    result = {
        "version": workflow.get("version"), "status": workflow.get("status", "not_built"),
        "first_result": {key: first[key] for key in ("metric", "score", "rows") if key in first},
        "checks": [{key: check[key] for key in ("id", "status", "label", "detail", "blocking") if key in check}
                   for check in workflow.get("checks", [])[:50] if isinstance(check, dict)],
        "artifacts": [{"name": item["name"]} for item in workflow.get("artifacts", [])[:100]
                      if isinstance(item, dict) and isinstance(item.get("name"), str)],
        "result_note": "Saved development trial only. A constant baseline is not reproduction of the named reference method. No final test result is supplied.",
    }
    return json.loads(onboarding_setup.redact_private(project, json.dumps(result)))


def _start_revision(project):
    state = ensure_conversation(project)
    if not state.get("readme"):
        raise ValueError("Create a draft before starting a revision.")
    if len(state["_revision_rounds"]) >= MAX_REVISION_ROUNDS:
        raise ValueError("This challenge has reached its 20-round review limit. Save the recorded work before starting a new challenge.")
    revision = {
        "number": len(state["_revision_rounds"]) + 1, "status": "awaiting_request",
        "requested_changes": [], "clarified_changes": [], "changed_fields": [],
        "followups": 0, "model_calls": 0, "asked_questions": [], "deferred_fields": [],
        "previous": {"readme": state["readme"], "items": copy.deepcopy(state["items"]),
                     "draft_meta": copy.deepcopy(state.get("_draft_meta")), "title": project.get("title"),
                     "workflow": _workflow_context(project)},
    }
    state["_revision_rounds"].append(revision)
    state.update(phase="revision", current_question=None, _pending=None)
    _reset_error(state)
    _message(state, "assistant", REVISION_MESSAGE)


def begin_revision(project, request_id, reserve=None):
    """Start an organizer-directed round without discarding any prior work."""
    _validate_request_id(request_id)
    state = ensure_conversation(project)
    if request_id in state["_requests"]:
        _request(state, request_id, "begin_revision")
        return
    if state["status"] != "idle" or state.get("_inflight") or state.get("_pending"):
        raise ValueError("Finish or retry the current response before starting a revision.")
    revision = _revision(state)
    if revision and revision["status"] != "draft_ready":
        _request(state, request_id, "begin_revision")
        return
    if not state.get("readme"):
        raise ValueError("Create a draft before starting a revision.")
    if len(state["_revision_rounds"]) >= MAX_REVISION_ROUNDS:
        raise ValueError("This challenge has reached its 20-round review limit.")
    _request(state, request_id, "begin_revision")
    _start_revision(project)
    if reserve:
        reserve(project)


def _understanding_label(score):
    return "Requirements met" if score == 100 else "Details missing" if score else "Not yet defined"


def _has_recorded_facts(value):
    """Exclude explicit unknown-only replies without discarding mixed answers.

    The model already assigns the checklist status from quoted source text.
    This narrow filter prevents a saved skip or unknown reply from filling a
    bar. It does not attempt to verify or reclassify scientific statements.
    """
    if not isinstance(value, str):
        return False
    unknown = {"", "unknown", "unsure", "not known", "not yet known", "not known yet", "not available", "none known", "no idea", "tbd",
               "to be determined", "n/a", "not yet", "deferred", "defer", "later", "to discuss", "undecided", "not decided", "not decided yet", "not yet decided"}
    names = {part.lower() for item in ITEMS for part in item[:2]} | {"baseline", "reference", "method", "metric"}
    # Split explicit contrasts so uncertainty does not hide a separate fact:
    # "The method is X, but its score is unknown" still records method X.
    clauses = re.split(r"[\n;]+|[.!?](?:\s+|$)|\s+(?:but|however|although)\s+", value, flags=re.IGNORECASE)
    for line in clauses:
        text = re.sub(r"\s+", " ", line.strip().lower().replace("’", "'")).strip(".,!? ")
        if _unknown(text) or text in unknown:
            continue
        # A named checklist item can precede an explicit unknown response.
        named = re.match(r"^([^:]+):\s*(.+)$", text)
        if named and named.group(1) in names:
            text = named.group(2).strip(".!? ")
            if _unknown(text) or text in unknown:
                continue
        # Recognize named unknown-only replies from older records as well.
        if any(text in {f"unknown {name}", f"{name} is unknown", f"the {name} is unknown",
                        f"i don't know the {name}", f"i do not know the {name}", f"no known {name}"}
               for name in names):
            continue
        if re.fullmatch(r"(?:i|we) (?:do not|don't|cannot|can't) know(?:\s+.*)?", text):
            continue
        if re.fullmatch(r"(?:(?:i am|we are|i'm|we're) )?(?:not sure|unsure|undecided)(?:\s+.*)?", text):
            continue
        if re.fullmatch(r"(?:i|we) (?:have not|haven't) decided(?:\s+.*)?", text):
            continue
        uncertainty = r"(?:unknown|not (?:yet )?known|undecided|not (?:yet )?decided|to be determined)"
        if re.fullmatch(r".+? (?:is|are|remains?|was|were) " + uncertainty + r"(?: yet| for now| to (?:me|us))?", text):
            continue
        return True
    return False


def _item_understanding(key, item):
    return readiness.item_understanding(key, item)


def _requirement_view(key, item):
    records = item.get("requirements", {})
    result = []
    for criterion in readiness.REQUIREMENTS[key]:
        record = records.get(criterion["id"], {})
        if key in readiness.SERVER_FIELDS:
            complete = readiness.item_understanding(key, item)["score"] == 100
            record = {"status": "recorded" if complete else "missing", "value": item["value"],
                      "evidence": [], "reason": "" if complete else item["gap"]}
        elif record.get("status") in {"recorded", "not_applicable"}:
            complete, reason = readiness.criterion_result(key, item, criterion)
            if not complete:
                record = {**record, "status": "missing", "reason": reason}
        bypass = readiness.bypass_record(key, item, criterion["id"])
        resolution = readiness.scope_resolution(key, item, criterion["id"])
        visible = {**criterion, "status": "missing", "value": "", "evidence": [], "reason": criterion["description"], **copy.deepcopy(record),
                   "can_bypass": readiness.can_bypass(key, criterion["id"]), "bypass": copy.deepcopy(bypass),
                   "can_delegate": readiness.can_delegate(key, criterion["id"]),
                   "delegation_policy": readiness.DELEGATION_POLICIES.get((key, criterion["id"])),
                   "resolution": copy.deepcopy(resolution)}
        if resolution:
            visible.update(status=resolution["mode"], value=resolution["detail"], reason=resolution.get("policy", ""))
        if bypass:
            visible.update(status="bypassed", reason=bypass["reason"])
        result.append(visible)
    return result


def sync_legacy_answers(project, manual_fields=()):
    """Copy complete recorded chat facts into the old audit answer fields.

    Call explicitly after chat mutations and before the legacy data audit.
    Call after manual answer edits with their field names in ``manual_fields``.
    The return value reports changes made to answer values, so the caller can
    invalidate an earlier audit or package. This helper performs no I/O.

    Source text is copied whole. Assessed items need genuine evidence for the
    mapped fact. A manual bypass cannot supply that evidence. Older items use
    their recorded status until assessed. Data declarations and budgets are untouched.
    """
    from .policy import known

    fields = {"objective": "question", "prediction_unit": "task", "success_criterion": "task"}
    criteria_by_answer = {"objective": ("scope",), "prediction_unit": ("inputs", "outputs"),
                          "success_criterion": ("metric",)}
    state = project.get("conversation")
    items = state.get("items", {}) if isinstance(state, dict) else {}
    answers = project.get("answers")
    if not isinstance(answers, dict):
        answers = {}
    previous_records = project.get("_chat_derived_answers", {})
    records = copy.deepcopy(previous_records) if isinstance(previous_records, dict) else {}
    previous_manual = project.get("_chat_manual_answers", [])
    manual = set(previous_manual) if isinstance(previous_manual, list) else set()
    manual.update(key for key in manual_fields if key in fields)
    changed = False
    for key, source in fields.items():
        record = records.get(key)
        tracked = isinstance(record, dict) and "value" in record
        current = answers.get(key)
        # A different value is a manual takeover, even if it is blank. Keep
        # that choice across later calls and later chat corrections.
        if tracked and current != record["value"]:
            manual.add(key)
        if key in manual:
            records.pop(key, None)
            continue
        if not tracked and current not in (None, ""):
            continue
        item = items.get(source, {})
        value = item.get("value", "") if isinstance(item, dict) else ""
        complete = isinstance(item, dict) and isinstance(value, str) and known(value)
        if complete and ("requirements" in item or item.get("bypasses")):
            # Count the evidence beneath a bypass. An exception for one detail
            # must neither invent that fact nor erase other supported facts.
            underlying = {name: content for name, content in item.items() if name not in {"bypasses", "scope"}}
            criteria = [criterion for criterion in readiness.REQUIREMENTS[source]
                        if criterion["id"] in criteria_by_answer[key]]
            complete = all(readiness.criterion_result(source, underlying, criterion)[0] for criterion in criteria)
        elif complete:
            complete = item.get("status") == "answered"
        replacement = value if complete else ""
        if not complete and not tracked:
            continue
        if current != replacement:
            answers[key] = replacement
            project["answers"] = answers
            changed = True
        records[key] = {"source_item": source, "value": replacement}
    if records != previous_records:
        project["_chat_derived_answers"] = records
    if set(previous_manual if isinstance(previous_manual, list) else []) != manual:
        project["_chat_manual_answers"] = sorted(manual)
    return changed


def recover_interrupted(project):
    state = project.get("conversation")
    if not isinstance(state, dict) or not state.get("_inflight"):
        return False
    retry = bool(state.get("_pending")) and _call_count(project) < MAX_CALLS
    state.update(_inflight=False, status="error", error="The response was interrupted. Your message and recorded answers are saved. " + ("Retry to continue." if retry else "Create a draft from the saved answers."), can_retry=retry)
    return True


def _validate_request_id(request_id):
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 100:
        raise ValueError("Use a nonempty request ID of at most 100 characters.")


def _request(state, request_id, action, text=""):
    _validate_request_id(request_id)
    fingerprint = hashlib.sha256(json.dumps([action, text]).encode()).hexdigest()
    prior = state["_requests"].get(request_id)
    if prior:
        if prior != fingerprint:
            raise ValueError("This request ID was already used for a different action.")
        return False
    if len(state["_requests"]) >= 200:
        raise ValueError("This conversation has reached its 200-action limit. Save the README and start a new challenge.")
    state["_requests"][request_id] = fingerprint
    state["_automatic_repair_used"] = False
    return True


def _reset_error(state):
    state.update(status="idle", error=None, can_retry=False, _inflight=False)
    state.pop("error_code", None)


def _fail(state, exc, can_retry=True):
    ending = "Retry, or create a draft from the saved answers." if can_retry else "The model call limit was reached. Create a draft from the saved answers."
    if isinstance(exc, ModelResponseError):
        cause = ("The model could not match its answer to the recorded evidence. "
                 if any(word in exc.code for word in ("evidence", "source", "correction", "replacement", "conflict", "superseded"))
                 else "The model returned an invalid or incomplete response format. ")
        state["error_code"] = exc.code
    else:
        cause = "The model service did not complete the request. "
        state["error_code"] = "model_service_failure"
    state.update(status="error", error=cause + "Your message and recorded answers are saved. " + ending, can_retry=can_retry, _inflight=False)


def _unknown(text):
    return text.strip().lower().rstrip(".!?") in {"i don't know", "i don’t know", "i do not know", "i do not know yet", "i don't know yet", "i don’t know yet", "unknown", "not sure", "not sure yet", "i'm not sure", "i’m not sure", "skip", "skip this", "skip this question", "pass"}


def _draft_command(text):
    return bool(re.fullmatch(r"(?:please\s+)?(?:make|create|generate|show|write)?\s*(?:a\s+|the\s+)?(?:draft(?:\s+readme)?|readme)(?:\s+now)?[.!]?", text.strip(), re.IGNORECASE))


def _scope_schema():
    quote = {"type": "string", "minLength": 1, "maxLength": 12000}
    return {"type": "object", "additionalProperties": False, "properties": {
        "updates": {"type": "array", "maxItems": len(ITEMS), "items": {"type": "object", "additionalProperties": False, "properties": {
            "field": {"type": "string", "enum": [key for key in BY_ID if key not in onboarding_setup.ITEM_FIELDS]}, "status": {"type": "string", "enum": ["partial", "answered", "deferred"]},
            "operation": {"type": "string", "enum": ["append", "correct"]}, "evidence": {"type": "array", "minItems": 1, "maxItems": 8, "items": quote},
            "supersedes": {"type": "array", "maxItems": 8, "items": quote}, "remaining_gap": {"type": "string", "maxLength": 1000}},
            "required": ["field", "status", "operation", "evidence", "supersedes", "remaining_gap"]}},
        "requirements": {"type": "array", "maxItems": sum(map(len, readiness.REQUIREMENTS.values())), "items": {"type": "object", "additionalProperties": False, "properties": {
            "field": {"type": "string", "enum": [key for key in BY_ID if key not in readiness.SERVER_FIELDS and key not in AGENT_OWNED_FIELDS]},
            "id": {"type": "string", "enum": sorted({c["id"] for criteria in readiness.REQUIREMENTS.values() for c in criteria})}, "status": {"type": "string", "enum": ["recorded", "missing", "deferred", "not_applicable", "conflicting"]},
            "evidence": {"type": "array", "maxItems": 8, "items": quote}, "reason": {"type": "string", "maxLength": 1000}},
            "required": ["field", "id", "status", "evidence", "reason"]}},
        "question_field": {"type": "string", "enum": ["", *BY_ID]}, "question_text": {"type": "string", "maxLength": 500},
        "question_requirement_id": {"type": "string", "enum": ["", *sorted({c["id"] for criteria in readiness.REQUIREMENTS.values() for c in criteria})]}, "question_why": {"type": "string", "maxLength": 1000}},
        "required": ["updates", "requirements", "question_field", "question_text", "question_requirement_id", "question_why"]}


def _draft_schema():
    return {"type": "object", "additionalProperties": False, "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 160}, "intro": {"type": "string", "maxLength": 1200}, "next_actions": {"type": "array", "maxItems": 5, "items": {"type": "string", "minLength": 1, "maxLength": 500}}}, "required": ["title", "intro", "next_actions"]}


def _saved_project_context(project):
    """Expose selected organizer metadata, never dataset rows or final answers.

    Data tools are a second input path. Their stored declarations help the
    interviewer avoid asking the same question again. Default design choices
    are identified as configuration, not confirmed scientific decisions.
    """
    source = project.get("dataset") or {}
    dataset = {key: source[key] for key in ("filename", "rows", "size_bytes") if key in source}
    if isinstance(source.get("columns"), list):
        dataset["columns"] = [{key: column[key] for key in ("name", "dtype") if key in column}
                              for column in source["columns"][:200] if isinstance(column, dict)]
    answers = project.get("answers") or {}
    declared = {key: answers[key] for key in ("objective", "prediction_unit", "success_criterion", "data_origin", "labels_public", "rights", "compute_budget", "token_budget")
                if answers.get(key) not in (None, "", "unknown")}
    design = project.get("design") or {}
    configuration = {key: design[key] for key in ("target", "task", "metric", "split", "group_column", "time_column", "exclude_columns") if key in design}
    analysis = project.get("analysis") or {}
    baseline = analysis.get("baseline") or {}
    development = {key: baseline[key] for key in ("status", "metric", "score", "dummy_score", "validation_rows") if key in baseline}
    context = {"dataset_metadata": dataset, "organizer_declarations": declared,
               "configured_design": configuration,
               "design_note": "Configuration can include defaults. It does not establish scientific approval.",
               "development_baseline": development,
               "baseline_note": "A bounded development check, not reproduction of the named reference method or a final score."}
    return json.loads(onboarding_setup.redact_private(project, json.dumps(context)))


def _platform_context(project):
    """Supply fixed application rules, separately from researcher evidence.

    This does not inspect a cluster, claim a completed trial, or fill answers.
    Keep these values aligned with workflow.py and the fixed runner contract.
    """
    from .runner.civo import APPROVED_IMAGE
    return {
        "source": "Application contract; these are fixed rules, not evidence of completed work.",
        "organizer_settings": onboarding_setup.get(project, include_private=False),
        "submission": {"format": "CSV", "columns": ["_autokaggle_id", "prediction"],
                       "rows": "Exactly one prediction per supplied input ID; no missing or duplicate IDs.",
                       "values": "Class labels, probabilities, or finite numbers according to the chosen task and metric."},
        "code_competition": {
            "entrypoint": "python predict.py --input INPUT.csv --output predictions.csv",
            "training_path": "/input/train.csv", "test_input_path": "/input/test_features.csv",
            "output_path": "/output/predictions.csv", "python": "3.12", "image": APPROVED_IMAGE,
            "dependencies": "Python standard library only; no package installation or network access.",
            "resources": {"cpu": 1, "memory_mib": 512, "cpu_seconds": 90, "program_seconds": 100, "job_seconds": 120, "gpu": 0},
            "visibility": "Submitted code receives hidden test inputs. Private answer labels stay in a separate trusted scorer. Participants receive representative examples.",
        },
        "prediction_competition": "Participants receive test inputs without answer labels and submit prediction CSV files.",
        "evaluation": "The final test is 20% and training is 80%. Development validation is drawn from the training portion. The scientist must choose an appropriate random, group, or time split and metric.",
        "feedback": "Participants receive aggregate development scores. Final answers and scores stay private. Quotas apply per team per UTC day and reset at 00:00 UTC.",
        "application_work": ["Generate dataset hashes, schemas, example submission, fixed environment specification, README, website draft, and researcher ZIP.",
                             "Run data checks and a first measured trial when prerequisites and runtime acceptance pass; report the actual result for organizer review."],
        "scientist_decisions": "Scientific task, useful metric and success threshold, data provenance and permissions, scientific split suitability, leakage risks, expected compute and token costs, ownership, review, and participant support.",
    }


def _provider(project, kind, context, reserve):
    state = ensure_conversation(project)
    if _call_count(project) >= MAX_CALLS:
        raise ValueError("The 12-call model limit has been reached.")
    project["_model_calls"] = project.get("_model_calls", 0) + 1
    revision = _revision(state)
    if revision:
        revision["model_calls"] += 1
    state["_inflight"] = True
    if reserve:
        reserve(project)
    from openai import OpenAI
    instructions = (Path(__file__).parent / "prompts/conversation.md").read_text()
    if revision:
        instructions += "\n\n" + (Path(__file__).parent / "prompts/revision.md").read_text()
    provider_input = onboarding_setup.redact_private(project, json.dumps({"mode": kind, **context, "platform_context": _platform_context(project)}, ensure_ascii=False))
    with OpenAI(timeout=120, max_retries=0) as client:
        response = client.responses.create(model=advisor.model_name(), reasoning={"effort": "high" if kind == "draft" else "medium"},
            instructions=instructions, input=provider_input,
            max_output_tokens=10000 if kind == "scope" else 1600,
            text={"format": {"type": "json_schema", "name": "onboarding_" + kind, "strict": True, "schema": _scope_schema() if kind == "scope" else _draft_schema()}})
    if response.status != "completed" or not response.output_text:
        raise ModelResponseError("Incomplete model response")
    try:
        return json.loads(response.output_text)
    except (json.JSONDecodeError, TypeError):
        raise ModelResponseError("Invalid JSON response") from None


def _evidence(text, current):
    if not isinstance(text, str) or not text.strip():
        raise ModelResponseError("Evidence must be source text")
    if text in current:
        return text
    if len(text) > 2 and (text[0], text[-1]) in {('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")} and text[1:-1] in current:
        return text[1:-1]
    raise ModelResponseError("Evidence was not in the current user message")


def _validate_scope(parsed, current, state):
    # Older saved/test provider responses can be read, but cannot establish
    # requirement completion. The live provider schema requires assessments.
    if not isinstance(parsed, dict) or not {"updates", "question_field", "question_text"} <= set(parsed) or set(parsed) - {"updates", "requirements", "question_field", "question_text", "question_requirement_id", "question_why"}:
        raise ModelResponseError("Invalid conversation response")
    if not isinstance(parsed["updates"], list) or len(parsed["updates"]) > len(ITEMS):
        raise ModelResponseError("Invalid updates")
    # Question wording and routing are presentation. Repair them only after
    # every factual update and requirement passes validation.
    seen, updates = set(), []
    for update in parsed["updates"]:
        if not isinstance(update, dict) or set(update) != {"field", "status", "operation", "evidence", "supersedes", "remaining_gap"}:
            raise ModelResponseError("Invalid field update")
        key, status, operation = update["field"], update["status"], update["operation"]
        if isinstance(key, str) and key in seen:
            raise ModelResponseError("Duplicate field update")
        if not isinstance(key, str) or key not in BY_ID or key in onboarding_setup.ITEM_FIELDS or not isinstance(status, str) or status not in {"partial", "answered", "deferred"} or not isinstance(operation, str) or operation not in {"append", "correct"}:
            raise ModelResponseError("Invalid field or status")
        if not isinstance(update["remaining_gap"], str) or len(update["remaining_gap"]) > 1000:
            raise ModelResponseError("Invalid remaining gap")
        if status == "answered" and update["remaining_gap"].strip():
            raise ModelResponseError("Answered items cannot retain a gap")
        if not isinstance(update["evidence"], list) or not 1 <= len(update["evidence"]) <= 8:
            raise ModelResponseError("Updates need source evidence")
        evidence = [_evidence(value, current) for value in update["evidence"]]
        if operation == "append":
            evidence = list(dict.fromkeys(evidence))
        supersedes = update["supersedes"]
        if not isinstance(supersedes, list) or len(supersedes) > 8 or any(not isinstance(x, str) or not x or len(x) > 12000 for x in supersedes):
            raise ModelResponseError("Invalid correction excerpts")
        if operation == "append" and supersedes:
            raise ModelResponseError("An append cannot remove previous facts")
        if operation == "correct" and not re.search(r"\b(correction|correcting|actually|instead|replace|revise|update|change|now|meant|wrong|should be)\b", current, re.IGNORECASE):
            raise ModelResponseError("A replacement needs an explicit correction")
        if operation == "correct":
            old = state["items"][key]["value"]
            confirmations = [resolution["detail"] for criterion in readiness.REQUIREMENTS[key]
                             if (resolution := readiness.scope_resolution(key, state["items"][key], criterion["id"])) and resolution["mode"] == "confirmed"]
            old = "\n".join([old, *dict.fromkeys(text for text in confirmations if text not in old)])
            if not supersedes or len(supersedes) != len(evidence) or any(old.count(x) != 1 for x in supersedes):
                raise ModelResponseError("Corrections must identify exact, unique prior spans")
            spans = sorted((old.index(x), old.index(x) + len(x)) for x in supersedes)
            if any(first[1] > second[0] for first, second in zip(spans, spans[1:])):
                raise ModelResponseError("Correction spans overlap")
        seen.add(key)
        updates.append({**update, "evidence": evidence})
    return updates


def _validate_requirements(parsed, current, state, updates):
    records = parsed.get("requirements", [])
    if not isinstance(records, list) or len(records) > sum(map(len, readiness.REQUIREMENTS.values())):
        raise ModelResponseError("Invalid requirement assessments")
    prospective = copy.deepcopy(state)
    _apply(prospective, updates, "assessment-preview")
    fact_sources = [current] + [item.get("value", "") for key, item in prospective["items"].items()
                           if key not in readiness.SERVER_FIELDS and key not in AGENT_OWNED_FIELDS]
    fact_sources += [message["content"] for message in state["messages"] if message.get("role") == "user"]
    scope_sources = [{"field": field, "requirement_id": criterion["id"], "detail": r["detail"], "version": item["scope"]["version"]}
                     for field, item in prospective["items"].items() for criterion in readiness.REQUIREMENTS[field]
                     if (r := readiness.scope_resolution(field, item, criterion["id"])) and r["mode"] == "confirmed"]
    sources = fact_sources + [source["detail"] for source in scope_sources]
    seen, clean = set(), []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"field", "id", "status", "evidence", "reason"}:
            raise ModelResponseError("Invalid requirement record")
        field, identifier, status = record["field"], record["id"], record["status"]
        if not isinstance(field, str) or field not in readiness.REQUIREMENTS or field in readiness.SERVER_FIELDS or field in AGENT_OWNED_FIELDS:
            raise ModelResponseError("Requirement is not model-owned")
        criterion = next((c for c in readiness.REQUIREMENTS[field] if c["id"] == identifier), None)
        if isinstance(identifier, str) and (field, identifier) in seen:
            raise ModelResponseError("Duplicate requirement assessment")
        if not isinstance(identifier, str) or not criterion or not isinstance(status, str) or status not in {"recorded", "missing", "deferred", "not_applicable", "conflicting"}:
            raise ModelResponseError("Invalid requirement identifier or status")
        if not isinstance(record["reason"], str) or len(record["reason"]) > 1000:
            raise ModelResponseError("Invalid requirement reason")
        accepted = readiness.scope_resolution(field, state["items"][field], identifier)
        if accepted and accepted["mode"] in {"delegated", "exception"} and status in {"recorded", "not_applicable"}:
            # A redundant model assessment cannot promote a bounded delegation
            # or explicit exception into a scientific fact, or fail the turn.
            seen.add((field, identifier))
            continue
        evidence = record["evidence"]
        if not isinstance(evidence, list) or len(evidence) > 8 or any(not isinstance(q, str) or not q.strip() or not any(q in source for source in sources) for q in evidence):
            raise ModelResponseError("Requirement evidence was not in the recorded research statements")
        if status in {"recorded", "not_applicable"} and not evidence:
            raise ModelResponseError("Completed requirements need source evidence")
        if status in {"recorded", "not_applicable"} and not _has_recorded_facts("\n".join(evidence)):
            raise ModelResponseError("Unknown answers cannot complete a requirement")
        retired = prospective.get("_superseded_evidence", [])
        replacements = [_replacement_text(span, quote) for update in updates if update["operation"] == "correct"
                        for span, quote in zip(update["supersedes"], update["evidence"])]
        if any(any(old in quote or quote in old for old in retired) and not any(quote in replacement for replacement in replacements)
               for quote in evidence):
            raise ModelResponseError("Superseded evidence cannot complete a requirement")
        if status == "not_applicable" and (not criterion["allow_not_applicable"] or not record["reason"].strip()):
            raise ModelResponseError("This requirement cannot be omitted without an allowed reason")
        if status in {"missing", "deferred"} and not record["reason"].strip():
            raise ModelResponseError("Open requirements need a specific gap")
        previous = state["items"][field].get("requirements", {}).get(identifier, {})
        explicit_correction = bool(accepted and accepted["mode"] == "confirmed" and status in {"missing", "deferred"}
            and any(quote in current for quote in evidence)
            and any(update["field"] == field and any(quote in update["evidence"] for quote in evidence) for update in updates)
            and re.search(r"\b(correction|correcting|actually|instead|replace|revise|update|change|now|meant|wrong|should be)\b", current, re.I))
        if status == "conflicting":
            prior = _source_quotes(previous)
            resolved = readiness.scope_resolution(field, state["items"][field], identifier)
            if resolved and resolved["mode"] == "confirmed":
                prior.append(resolved["detail"])
            old = [quote for quote in evidence if any(quote in source for source in prior) and quote not in current]
            new = [quote for quote in evidence if quote in current and not any(quote in source for source in prior) and _has_recorded_facts(quote)]
            if not record["reason"].strip() or not old or not new:
                raise ModelResponseError("A conflict needs prior and new source evidence for this requirement")
        if previous.get("status") == "conflicting" and status in {"recorded", "not_applicable"} and not any(q in current for q in evidence):
            continue
        seen.add((field, identifier))
        dependencies = [source for source in scope_sources if any(quote in source["detail"] and not any(quote in fact for fact in fact_sources) for quote in evidence)]
        clean.append({**record, "evidence": list(dict.fromkeys(evidence)), "value": "\n".join(dict.fromkeys(evidence)),
                      "scope_sources": dependencies, "explicit_correction": explicit_correction})
    return clean


def _repair_question(parsed, state, updates, requirements):
    """Replace invalid presentation with an exact, server-owned open criterion."""
    field, text = parsed["question_field"], parsed["question_text"]
    identifier, why = parsed.get("question_requirement_id", ""), parsed.get("question_why", "")
    prospective = copy.deepcopy(state)
    _apply(prospective, updates, "question-preview")
    if "requirements" in parsed:
        _apply_requirements(prospective, requirements)
    valid_field = isinstance(field, str) and field in BY_ID and field not in AGENT_OWNED_FIELDS
    valid_strings = all(isinstance(value, str) for value in (text, identifier, why))
    empty = field == "" and valid_strings and not any(value.strip() for value in (text, identifier, why))
    criterion = _target_criterion(prospective, field, parsed) if valid_field else None
    valid = (valid_field and valid_strings and bool(text.strip()) and len(text) <= 500
             and len(why) <= 1000 and text.count("?") <= 1 and "\n" not in text
             and ("question_requirement_id" not in parsed or bool(criterion and criterion["id"] == identifier))
             and ("question_why" not in parsed or bool(why.strip())))
    if empty or valid:
        return parsed
    revision = _revision(prospective)
    if revision:
        candidates = [field] if valid_field else []
        active = state.get("current_question") or state.get("scope_checkpoint") or {}
        candidates += [active.get("field"), *revision["changed_fields"]]
        candidates = [key for key in candidates if key in BY_ID and key not in AGENT_OWNED_FIELDS
                      and key not in revision["deferred_fields"]]
    else:
        candidates = _eligible(prospective)
        if valid_field and field in candidates:
            candidates = [field, *[key for key in candidates if key != field]]
    target = next(((key, _target_criterion(prospective, key)) for key in candidates
                   if _target_criterion(prospective, key)), None)
    repaired = {**parsed, "question_field": "", "question_requirement_id": "", "question_text": "", "question_why": ""}
    if target:
        key, criterion = target
        repaired.update(question_field=key, question_requirement_id=criterion["id"],
                        question_text=f"Please define {criterion['label'].lower()} for this challenge. {criterion['description']}",
                        question_why=criterion["description"])
    _record_response_issue(state, "scope", "question_presentation_repaired", 0)
    return repaired


def _validated_scope(parsed, text, state):
    updates = _validate_scope(parsed, text, state)
    requirements = _validate_requirements(parsed, text, state, updates)
    return _repair_question(parsed, state, updates, requirements), updates, requirements


def _apply_requirements(state, records):
    for record in records:
        item = state["items"][record["field"]]
        criterion = next(c for c in readiness.REQUIREMENTS[record["field"]] if c["id"] == record["id"])
        explicit = readiness.scope_resolution(record["field"], item, record["id"])
        if record.get("explicit_correction"):
            previous = item.get("requirements", {}).get(record["id"], {})
            spans = _source_quotes(previous) + ([explicit["detail"]] if explicit else [])
            _invalidate_evidence(state, spans, "An explicit correction changed this organizer decision. Confirm the revised scope.")
            _stale_resolution(item, record["id"])
        if explicit and record["status"] in {"recorded", "not_applicable"} and record.get("scope_sources"):
            # Keep a model restatement of scope-only evidence in the scope layer.
            continue
        underlying = {key: value for key, value in item.items() if key not in {"bypasses", "scope"}}
        candidate = {"requirements": {record["id"]: record}}
        if record.get("scope_sources") and record["status"] != "conflicting" and readiness.criterion_result(record["field"], underlying, criterion)[0]:
            # A scope restatement must not replace independent source evidence.
            continue
        if record["status"] != "conflicting" and readiness.criterion_result(record["field"], underlying, criterion)[0] and not readiness.criterion_result(record["field"], candidate, criterion)[0]:
            # A partial assessment is not evidence that an earlier fact changed.
            continue
        if record["status"] == "conflicting":
            previous = item.get("requirements", {}).get(record["id"], {})
            _invalidate_evidence(state, _source_quotes(previous), "A supporting fact conflicts with a new statement. Confirm the intended decision.")
            _stale_resolution(item, record["id"])
        item.setdefault("requirements", {})[record["id"]] = {k: copy.deepcopy(record[k]) for k in ("status", "value", "evidence", "reason")}
        if record.get("scope_sources"):
            item["requirements"][record["id"]]["scope_sources"] = copy.deepcopy(record["scope_sources"])
        if record["status"] in {"recorded", "not_applicable"}:
            if readiness.criterion_result(record["field"], {"requirements": item["requirements"]}, criterion)[0]:
                state.setdefault("_criterion_asks", {}).pop(record["field"] + "." + record["id"], None)
            for quote in record["evidence"]:
                scope_only = any(quote in source["detail"] for source in record.get("scope_sources", []))
                if quote not in item["value"] and not scope_only:
                    item["value"] = (item["value"] + "\n" + quote).strip()
    state["_requirements_assessed"] = True
    for key, item in state["items"].items():
        if key in readiness.SERVER_FIELDS or key in AGENT_OWNED_FIELDS:
            continue
        progress = readiness.item_understanding(key, item)
        if progress["completed"] == progress["total"]:
            item.update(status="answered", gap="")
        else:
            item["status"] = "partial" if _has_recorded_facts(item["value"]) or progress["completed"] else "missing"
            gaps = [c["label"] for c in readiness.REQUIREMENTS[key]
                    if not readiness.criterion_result(key, item, c)[0]]
            item["gap"] = "Required details: " + "; ".join(gaps) if key in readiness.REQUIRED_FIELDS else "Optional details: " + "; ".join(gaps)
            open_records = [item.get("requirements", {}).get(c["id"], {}) for c in readiness.REQUIREMENTS[key]
                            if not readiness.criterion_result(key, item, c)[0]]
            if open_records and all(record.get("status") == "deferred" for record in open_records):
                item["status"] = "deferred"


def _source_quotes(record):
    result = []
    for value in record.get("evidence", []):
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, dict):
            result.extend(q for q in value.get("quotes", []) if isinstance(q, str))
    return result


def _stale_resolution(item, identifier):
    scope = item.get("scope")
    if not isinstance(scope, dict):
        return
    for record in scope.get("resolutions", []):
        if record.get("requirement_id") == identifier:
            record["stale"] = True
            scope["stale"] = True


def _invalidate_evidence(state, spans, reason):
    for field, item in state["items"].items():
        for identifier, record in item.get("requirements", {}).items():
            if any(span in quote or quote in span for span in spans for quote in _source_quotes(record)):
                record.update(status="missing", reason=reason)
                state.setdefault("_criterion_asks", {}).pop(field + "." + identifier, None)
        scope = item.get("scope")
        if not isinstance(scope, dict):
            continue
        before = copy.deepcopy(scope)
        if any(span in quote or quote in span for span in spans for quote in scope.get("source_evidence", [])):
            scope["stale"] = True
        for record in scope.get("resolutions", []):
            cited = [*record.get("source_evidence", []), record.get("detail", "")]
            if any(span in quote or quote in span for span in spans for quote in cited if quote):
                record["stale"] = True
                scope["stale"] = True
                state.setdefault("_criterion_asks", {}).pop(field + "." + record["requirement_id"], None)
        if scope != before:
            state.setdefault("_scope_audit", []).append({"field": field, "action": "source_changed", "reason": reason,
                                                         "before": before, "after": copy.deepcopy(scope), "at": datetime.now(timezone.utc).isoformat()})


def _invalidate_scope_dependents(state, changed_field):
    for field, item in state["items"].items():
        for identifier, record in item.get("requirements", {}).items():
            for source in record.get("scope_sources", []):
                if source["field"] != changed_field:
                    continue
                current = readiness.scope_resolution(changed_field, state["items"][changed_field], source["requirement_id"])
                if not current or current["mode"] != "confirmed" or current["detail"] != source["detail"]:
                    record.update(status="missing", reason="The organizer scope decision supporting this detail changed or was removed.")
                    break


def _replacement_text(prior_span, evidence):
    """Keep context when an explicit correction changes one dollar amount.

    Evidence remains unchanged in the audit record. This helper changes only
    the displayed replacement, and performs no currency or number conversion.
    """
    amount = r"(?:\$\s*|USD\s+)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    transitions = list(re.finditer(r"\bfrom\s+(?P<old>" + amount + r")\s+to\s+(?P<new>" + amount + r")(?!\d|\.\d)", evidence, re.IGNORECASE))
    if len(transitions) == 1:
        old, new = transitions[0].group("old"), transitions[0].group("new")
        occurrences = list(re.finditer(re.escape(old) + r"(?!\d|\.\d)", prior_span))
        if len(occurrences) == 1:
            match = occurrences[0]
            return prior_span[:match.start()] + new + prior_span[match.end():]
    elif re.fullmatch(amount, evidence, re.IGNORECASE):
        amounts = list(re.finditer(amount + r"(?!\d|\.\d)", prior_span, re.IGNORECASE))
        if len(amounts) == 1:
            match = amounts[0]
            return prior_span[:match.start()] + evidence + prior_span[match.end():]
    return evidence


def _apply(state, updates, message_id):
    for update in updates:
        key, previous = update["field"], copy.deepcopy(state["items"][update["field"]])
        item = state["items"][key]
        quotes = update["evidence"]
        if update["operation"] == "correct":
            state.setdefault("_superseded_evidence", []).extend(span for span in update["supersedes"] if span not in state.get("_superseded_evidence", []))
            # Any derived requirement that cites a replaced fact must be
            # assessed again, including requirements in another checklist item.
            _invalidate_evidence(state, update["supersedes"], "A supporting fact changed. Check this requirement again.")
            old = item["value"]
            replacements = sorted((old.index(span), old.index(span) + len(span), _replacement_text(span, new)) for span, new in zip(update["supersedes"], quotes) if span in old)
            # Work backwards so earlier offsets remain valid. Only explicitly
            # superseded text is replaced; other facts remain recorded.
            for start, end, new in reversed(replacements):
                old = old[:start] + new + old[end:]
            for span, new in zip(update["supersedes"], quotes):
                if span not in previous["value"]:
                    old = (old + "\n" + _replacement_text(span, new)).strip()
            item["value"] = old
        else:
            existing = item["value"].split("\n") if item["value"] else []
            item["value"] = "\n".join(dict.fromkeys([*existing, *quotes]))
        item["evidence"].append({"message_id": message_id, "quotes": quotes})
        item["_source_version"] = item.get("_source_version", 0) + 1
        item["status"] = update["status"]
        item["gap"] = update["remaining_gap"] if update["status"] != "answered" else ""
        if key in AGENT_OWNED_FIELDS and item["status"] == "answered":
            item["status"] = "partial"
            item["gap"] = "Researcher statement recorded. Application execution evidence is still required."
        if item["status"] != "answered" and not item["gap"]:
            item["gap"] = "Deferred by the researcher." if item["status"] == "deferred" else BY_ID[key][4]
        state["_history"].append({"field": key, "before": previous, "message_id": message_id, "operation": update["operation"], "supersedes": copy.deepcopy(update.get("supersedes", [])), "replacement_evidence": copy.deepcopy(quotes)})
        revision = _revision(state)
        if revision and key not in revision["changed_fields"]:
            revision["changed_fields"].append(key)
    if updates:
        state["readme"] = None
        state["_draft_meta"] = None


def _defer(state, field, text, message_id, requirement_id=None):
    assessed = state.get("_requirements_assessed", False)
    if not assessed:
        requirement_id = None
    _apply(state, [{"field": field, "status": "deferred", "operation": "append", "evidence": [text], "remaining_gap": "The researcher deferred this item. It needs review before release."}], message_id)
    if field not in state["_asked"]:
        state["_asked"].append(field)
    for criterion in readiness.REQUIREMENTS[field]:
        if (not requirement_id or criterion["id"] == requirement_id) and not readiness.criterion_result(field, state["items"][field], criterion)[0]:
            state["items"][field].setdefault("requirements", {})[criterion["id"]] = {
                "status": "deferred", "value": text, "evidence": [text],
                "reason": "The researcher does not know or deferred this detail. It remains open."}
    revision = _revision(state)
    _apply_requirements(state, [])
    if not assessed:
        state["_requirements_assessed"] = False
    if revision and state["items"][field]["status"] == "deferred" and field not in revision["deferred_fields"]:
        revision["deferred_fields"].append(field)


def _eligible(state):
    if state.get("_requirements_assessed"):
        return [key for key in QUESTION_ORDER if key in readiness.REQUIRED_FIELDS
                and _open_criteria(state, key)]
    return [key for key in QUESTION_ORDER if state["items"][key]["status"] in {"missing", "partial"} and key not in state["_asked"]]


def _partial_question(key, gap, fallback):
    """Keep a specific question, or turn a recorded gap into a short prompt."""
    line = gap.splitlines()[0].strip()
    if "?" in line:
        return line.split("?", 1)[0] + "?"
    text = line.lower()
    if key == "task" and re.search(r"\b(metric|score|success|threshold)\b", text):
        return "Which measure would show a useful result?"
    if key == "task" and re.search(r"\b(input|inputs|feature|features)\b", text):
        return "Which inputs would the solution receive?"
    if key == "data" and re.search(r"\b(label|labels|labeling|labelled|labeled)\b", text):
        return "How were the labels obtained?"
    if key == "data" and re.search(r"\b(source|sources|provenance|origin)\b", text):
        return "Where did these data come from?"
    return PARTIAL_QUESTIONS.get(key, fallback)


def _open_criteria(state, field, include_deferred=False):
    item = state["items"][field]
    return [criterion for criterion in readiness.REQUIREMENTS[field]
            if not readiness.criterion_result(field, item, criterion)[0]
            and (include_deferred or item.get("requirements", {}).get(criterion["id"], {}).get("status") != "deferred")]


def _target_criterion(state, field, suggestion=None):
    gaps = _open_criteria(state, field)
    wanted = (suggestion or {}).get("question_requirement_id")
    return next((criterion for criterion in gaps if criterion["id"] == wanted), gaps[0] if gaps else None)


def _checkpoint(state, field, criterion, reason=None):
    item = state["items"][field]
    record = item.get("requirements", {}).get(criterion["id"], {})
    checkpoint = {"field": field, "requirement_id": criterion["id"],
                  "reason": reason or record.get("reason") or criterion["description"],
                  "can_delegate": readiness.can_delegate(field, criterion["id"])}
    # A proposal may quote a saved decision. Never invent a scientific default.
    if record.get("value") and _has_recorded_facts(record["value"]):
        checkpoint["proposed_answer"] = record["value"]
    previous = state.get("scope_checkpoint")
    state.update(scope_checkpoint=checkpoint, current_question=None, _pending=None)
    _reset_error(state)
    if previous != checkpoint:
        _message(state, "assistant", f"We have not resolved {criterion['label'].lower()}. Open this checklist item to confirm the scope, record an explicit exception, or supply a new decision. I will not ask the same detail again automatically.")


def _needs_checkpoint(state):
    active = state.get("current_question") or state.get("scope_checkpoint")
    if not active or active.get("field") not in readiness.REQUIREMENTS:
        return False
    field, identifier = active["field"], active.get("requirement_id")
    criterion = next((c for c in readiness.REQUIREMENTS[field] if c["id"] == identifier), None)
    if not state.get("_requirements_assessed") and state["items"][field]["status"] == "answered":
        state["scope_checkpoint"] = None
        return False
    if criterion and not readiness.criterion_result(field, state["items"][field], criterion)[0] and state["_criterion_asks"].get(field + "." + identifier, 0) >= 2:
        _checkpoint(state, field, criterion)
        return True
    state["scope_checkpoint"] = None
    return False


def _ask(state, field, criterion, text, why=""):
    token = field + "." + criterion["id"]
    count = state["_criterion_asks"].get(token, 0)
    if count >= 2:
        _checkpoint(state, field, criterion)
        return
    if not text or text.count("?") > 1 or "\n" in text:
        text = f"Please define {criterion['label'].lower()} for this challenge. {criterion['description']}"
    if field == "data":
        text = _data_link_question(state, text, criterion["id"])
    normalized = re.sub(r"\W+", " ", text.lower()).strip()
    revision = _revision(state)
    asked = revision["asked_questions"] if revision else state["_asked_questions"]
    if normalized in asked:
        text = f"To settle {criterion['label'].lower()}, what decision should the challenge use?"
        normalized = re.sub(r"\W+", " ", text.lower()).strip()
    asked.append(normalized)
    state["_criterion_asks"][token] = count + 1
    state.update(phase="revision" if revision else "conversation", scope_checkpoint=None,
                 current_question={"field": field, "requirement_id": criterion["id"], "text": text,
                                   "why": why or criterion["description"]}, _pending=None)
    if revision:
        revision["followups"] += 1
        revision["status"] = "clarifying"
    else:
        state["_asked"].append(field)
        state["followups"] += 1
    _reset_error(state)
    _message(state, "assistant", text)


def _advance(project, reserve, suggestion=None, force_draft=False):
    state = ensure_conversation(project)
    if force_draft:
        _draft(project, reserve)
        return
    if _needs_checkpoint(state):
        return
    if _revision(state):
        _advance_revision(project, reserve, suggestion)
        return
    remaining = _eligible(state)
    if state["followups"] >= MAX_FOLLOWUPS or not remaining:
        _draft(project, reserve)
        return
    if any(key in CORE_FIELDS for key in remaining):
        remaining = [key for key in remaining if key in CORE_FIELDS or (key not in onboarding_setup.ITEM_FIELDS and BY_ID[key][2] != "Organizer settings")]
    key = suggestion["question_field"] if suggestion and suggestion.get("question_field") in remaining else remaining[0]
    criterion = _target_criterion(state, key, suggestion)
    if not criterion:
        _draft(project, reserve)
        return
    accurate_target = suggestion and suggestion.get("question_field") == key and suggestion.get("question_requirement_id") == criterion["id"]
    text = suggestion["question_text"].strip() if accurate_target else f"Please define {criterion['label'].lower()} for this challenge. {criterion['description']}"
    if not state.get("_requirements_assessed"):
        fallback = BY_ID[key][3]
        if state["items"][key]["status"] == "partial" and state["items"][key]["gap"]:
            fallback = _partial_question(key, state["items"][key]["gap"], fallback)
        text = suggestion["question_text"].strip() if suggestion and suggestion.get("question_field") == key else fallback
    if key in readiness.SERVER_FIELDS:
        text = BY_ID[key][3]
        if key == "submissions":
            text = f"Do you confirm {onboarding_setup.get(project)['daily_submission_limit']} submissions per day, or want a different daily limit?"
    _ask(state, key, criterion, text, suggestion.get("question_why", "") if accurate_target else "")


def _advance_revision(project, reserve, suggestion=None, force_draft=False):
    state = ensure_conversation(project)
    revision = _revision(state)
    field = suggestion.get("question_field") if suggestion else None
    if force_draft or revision["followups"] >= MAX_FOLLOWUPS or field not in BY_ID or field in AGENT_OWNED_FIELDS or field in revision["deferred_fields"]:
        _draft(project, reserve)
        return
    criterion = _target_criterion(state, field, suggestion)
    if not criterion or not suggestion.get("question_text"):
        _draft(project, reserve)
        return
    text = suggestion["question_text"].strip()
    if not state.get("_requirements_assessed") and re.sub(r"\W+", " ", text.lower()).strip() in revision["asked_questions"]:
        _draft(project, reserve)
        return
    if state.get("_requirements_assessed") and suggestion.get("question_requirement_id") != criterion["id"]:
        text = f"Please define {criterion['label'].lower()} for this challenge. {criterion['description']}"
    _ask(state, field, criterion, text, suggestion.get("question_why", ""))


def _quote(text):
    return "\n".join("> " + html.escape(line) for line in text.splitlines())


def _render(project):
    from .scope_exports import public_scopes, scope_text
    state = ensure_conversation(project)
    meta = state.get("_draft_meta") or {}
    title = project.get("title") if project.get("title") not in DEFAULT_TITLES else meta.get("title") or "Challenge design README"
    lines = ["# " + html.escape(title.replace("\n", " ")), "", "**Status: Draft — pending organizer review.**", "", "This document records researcher statements, organizer scope decisions, and explicit manual bypasses. Delegation and exceptions are separate from scientific evidence. A resolved item does not prove that checks, trials, or independent review were completed.", "", "Based on [Challenge design roadmap](https://data.mlr.press/assets/pdf/v02-10.pdf), Sections 1–2 and Appendix C.", ""]
    definition = readiness.assess(state)
    lines += ["## Definition readiness", "", readiness.DEFINITION, "",
              f"{definition['completed']} of {definition['total']} required details are resolved. Manual bypasses: {definition['bypassed']}.", "",
              f"Scope decisions: {definition['confirmed']} confirmed, {definition['delegated']} delegated, {definition['exception']} exceptions.", "",
              ("Definition accepted with recorded manual bypasses; technical preparation and organizer review remain." if definition["bypassed"] else
               "Challenge defined; technical preparation and organizer review remain.") if definition["ready"] else
              "Working draft only. Required decisions remain open. This draft does not establish readiness to run the challenge.", "",
              "A functional reference baseline is optional. Novel tasks without one are allowed. Evaluator and submission-process checks remain required.", ""]
    if definition["bypasses"]:
        lines += ["### Manual requirement bypasses", "", "These are explicit organizer decisions. They resolve the interview requirement without establishing the missing scientific fact. They do not waive application checks.", ""]
        for bypass in definition["bypasses"]:
            lines.append(f"- **Bypassed: {bypass['label']} — {bypass['requirement_label']}.** Reason: {html.escape(bypass['reason'])}")
        lines.append("")
    scopes = public_scopes(project)
    if scopes:
        lines += [scope_text(scopes), ""]
    if meta.get("intro"):
        lines += ["## Suggested framing", "", _quote(meta["intro"]), "", "This model-written summary needs review. The recorded answers below are authoritative.", ""]
    labels = {"missing": "Missing", "partial": "Partial", "answered": "Recorded", "deferred": "Deferred"}
    for pillar in PILLARS:
        lines += ["## " + pillar, ""]
        for key, label, group, _, _ in ITEMS:
            if group != pillar or key == "organizer":
                continue
            item = state["items"][key]
            understanding = readiness.item_understanding(key, item)
            item_label = understanding["label"] if item.get("scope") else "Resolved with bypass" if item["status"] == "answered" and understanding["bypassed"] else labels[item["status"]]
            lines += [f"### {label}", "", f"Status: {item_label}", "", _quote(item["value"]) if item["value"] else "No answer recorded.", ""]
            if item["gap"]:
                lines += ["Open item: " + html.escape(item["gap"]), ""]
            if key not in AGENT_OWNED_FIELDS:
                for criterion in readiness.REQUIREMENTS[key]:
                    complete, reason = readiness.criterion_result(key, item, criterion)
                    label = criterion["label"] + (" (optional)" if key in readiness.OPTIONAL_FIELDS else "")
                    bypass = readiness.bypass_record(key, item, criterion["id"])
                    resolution = readiness.scope_resolution(key, item, criterion["id"])
                    status_label = "Bypassed" if bypass else resolution["mode"].capitalize() if resolution else "Recorded" if complete else "Open"
                    lines.append(f"- {status_label}: {label}." +
                                 (" Reason: " + html.escape(bypass["reason"]) if bypass else " " + html.escape(reason) if not complete else ""))
                lines.append("")
    unresolved = list(dict.fromkeys(b["label"] for b in definition["blockers"] if b["field"] != "organizer"))
    if state.get("_unprocessed"):
        lines += ["## Messages awaiting manual review", "", "These messages were saved but have not been applied to the checklist.", ""]
        for pending in state["_unprocessed"]:
            lines += [_quote(pending["text"]), ""]
    setup = onboarding_setup.get(project)
    format_note = {"prediction": "Prediction competition: the researcher package must contain test inputs without answer labels. Participants return predictions in the specified format.",
                   "code": "Code competition: the researcher package must contain representative test examples. The evaluator must run submitted code on hidden test inputs and keep the answer labels separate."}.get(setup["competition_type"], "Competition format is not yet selected. Choose prediction or code before the package is built.")
    lines += ["## Required challenge artifacts", "", "These are requirements for later preparation. This draft does not establish that these files exist or that an evaluator has run.", "",
              "- Define the input/output contract, row identifiers, schema, and a valid example submission.",
              "- Record dataset versions, file hashes, split assignments, and the metric version.",
              "- Specify dependencies and the execution environment, including package versions.",
              "- Set CPU, GPU, time, and RAM limits. Record compute and model-token budgets in dollars.",
              "- Prepare the challenge website, researcher ZIP, and separate private evaluation materials as private drafts before organizer review.", "", format_note, "",
              f"Daily submission limit: {setup['daily_submission_limit']} ({'confirmed' if setup['submissions_confirmed'] else 'proposed; organizer confirmation required'}).", "",
              "## Review and first trial", "", "Keep the draft private for organizer review. Resolve feedback from the first complete submission-and-scoring trial before publication. Record the trial result and any fixes. Review, trial execution, email delivery, and publication remain planned until separate evidence confirms them.", "",
              "The application must test the evaluator and submission process on development data. A scientific reference baseline is optional. If one is available, report reproduction separately from the pipeline test and keep its reported score separate from measured results. A missing or nonfunctional reference does not block a novel challenge. Record any failed reproduction and its cause. Keep final holdout feedback protected.", "",
              "## Decision", "", "Pending organizer review. This draft does not approve a challenge for release.", ""]
    lines += ["Unresolved required items: " + ", ".join(unresolved) + "." if unresolved else
              "All required items are resolved. Review the evidence and any manual bypasses, then obtain organizer approval before release.", ""]
    actions = meta.get("next_actions") or (["Review the unresolved items and record evidence for each decision."] if unresolved else ["Verify the recorded statements and complete independent review."])
    lines += ["## Suggested next actions", "", *["- " + html.escape(action.replace("\n", " ")) for action in actions], ""]
    return onboarding_setup.redact_private(project, "\n".join(lines))


def _draft(project, reserve):
    state = ensure_conversation(project)
    state.update(phase="draft", current_question=None, _pending={"kind": "draft"})
    state["readme"] = _render(project)
    if not advisor.configured() or _call_count(project) >= MAX_CALLS:
        budget = _call_count(project) >= MAX_CALLS
        _reset_error(state)
        state["_pending"] = None
        if _revision(state):
            _revision(state)["status"] = "draft_ready"
        _message(state, "assistant", ("The 12-call model limit was reached. " if budget else "Rules mode: ") + "The draft README contains your recorded answers and open items. You can review it and send corrections.")
        return
    try:
        public_items = {key: value for key, value in state["items"].items() if key != "organizer"}
        public_items = json.loads(onboarding_setup.redact_private(project, json.dumps(public_items)))
        context = {"recorded_items": public_items, "title": onboarding_setup.redact_private(project, project.get("title", "")), "instruction": "Suggest framing and next actions only. The server renders the answers and decision. Artifact preparation, private organizer review, and first-trial feedback are requirements; do not claim they happened."}
        if _revision(state):
            context["revision_context"] = _revision_context(project)
        parsed = _validated_response(project, "draft", context, reserve, _validate_draft)
        state["_draft_meta"] = parsed
        if project.get("title") in DEFAULT_TITLES or project.get("title") == state.get("_generated_title"):
            project["title"] = parsed["title"].replace("\n", " ").strip()
            state["_generated_title"] = project["title"]
        state["readme"] = _render(project)
        state["_pending"] = None
        _reset_error(state)
        if _revision(state):
            _revision(state)["status"] = "draft_ready"
            _message(state, "assistant", "The revised working draft is saved. It includes the recorded changes and open required details. Build the workflow again to update the website, package, and submission trial.")
        else:
            definition = readiness.assess(state)
            _message(state, "assistant", "The working draft is saved. " +
                     (("All required decisions are resolved, including manual bypasses. Review the bypass reasons before building the package for technical checks and organizer review." if definition["bypassed"] else
                       "All required decisions are recorded. Build the package for technical checks and organizer review.") if definition["ready"] else
                      f"{len(definition['blockers'])} required details remain open. Select Continue interview to work through them, or send a correction. A reference baseline is optional."))
    except Exception as exc:
        _fail(state, exc, _call_count(project) < MAX_CALLS)


def _validate_draft(parsed):
    if not isinstance(parsed, dict) or set(parsed) != {"title", "intro", "next_actions"}:
        raise ModelResponseError("Invalid draft metadata")
    if not isinstance(parsed["title"], str) or not parsed["title"].strip() or len(parsed["title"]) > 160 or not isinstance(parsed["intro"], str) or len(parsed["intro"]) > 1200:
        raise ModelResponseError("Invalid draft framing")
    if not isinstance(parsed["next_actions"], list) or len(parsed["next_actions"]) > 5 or any(not isinstance(x, str) or not x.strip() or len(x) > 500 for x in parsed["next_actions"]):
        raise ModelResponseError("Invalid next actions")
    return parsed


def _revision_context(project):
    state = ensure_conversation(project)
    revision = _revision(state)
    previous = revision["previous"]
    context = {
        "round": revision["number"], "requested_changes": revision["requested_changes"],
        "clarified_changes": revision["clarified_changes"], "changed_fields": revision["changed_fields"],
        "previous_readme": previous["readme"], "previous_title": previous["title"],
        "previous_workflow": previous["workflow"], "current_workflow": _workflow_context(project),
        "conversation_history": [{"role": message["role"], "content": message["content"]} for message in state["messages"]],
        "previous_rounds": [{"round": item["number"], "requested_changes": item["requested_changes"],
                             "clarified_changes": item["clarified_changes"], "changed_fields": item["changed_fields"]}
                            for item in state["_revision_rounds"][:-1]],
        "change_policy": "Follow only the organizer's requested changes and their necessary consequences. Ask one specific clarification when needed. Existing unrelated gaps remain open. Saved results apply to the previous version; a revised workflow needs new checks."
    }
    return json.loads(onboarding_setup.redact_private(project, json.dumps(context)))


def _rules_method_change(state, field, text):
    """Reopen an explicitly directed method restriction in rules mode.

    This limited route records that a decision changed. It does not infer a
    replacement scientific policy or invalidate unrelated resource decisions.
    """
    if field != "methodology" or not re.search(r"\b(require|must|only|prohibit|forbid|allow|replace|instead|change|use)\b", text, re.I):
        return
    targets = []
    if re.search(r"\b(external (?:data|datasets?|services?)|pretrained (?:models?|weights?))\b", text, re.I):
        targets.append("resources")
    method_text = re.sub(r"\bpretrained models?\b", "", text, flags=re.I)
    if re.search(r"\b(methods?|models?|algorithms?|approaches?|networks?|linear|neural)\b", method_text, re.I):
        targets.append("methods")
    item = state["items"][field]
    for identifier in targets:
        previous = item.get("requirements", {}).get(identifier, {})
        resolution = readiness.scope_resolution(field, item, identifier)
        if not previous and not resolution:
            continue
        spans = _source_quotes(previous) + ([resolution["detail"]] if resolution else [])
        reason = "The organizer directed a new restriction in rules mode. Confirm this requirement or assess the saved change."
        _invalidate_evidence(state, spans, reason)
        _stale_resolution(item, identifier)
        item.setdefault("requirements", {})[identifier] = {**previous, "status": "missing", "reason": reason}
    if targets:
        _apply_requirements(state, [])


def _process_message(project, reserve):
    state = ensure_conversation(project)
    pending = state["_pending"]
    text, message_id, current = pending["text"], pending["message_id"], pending["field"]
    revision = _revision(state)
    was_draft = pending["was_draft"] and not revision
    if _draft_command(text):
        _draft(project, reserve)
        return
    labelled = re.match(r"^([A-Za-z ]+)\s*:\s*(.+)$", text, re.DOTALL)
    labelled_key = onboarding_setup.LABELS.get(labelled[1].strip().lower(), labelled[1].strip().lower()) if labelled else None
    explicit_unknown = labelled_key in BY_ID and _unknown(labelled.group(2)) if labelled else False
    if _unknown(text) or explicit_unknown:
        field = labelled_key if explicit_unknown else current or (None if was_draft or revision else "question")
        if field is None:
            state["_unprocessed"] = [m for m in state.get("_unprocessed", []) if m["message_id"] != message_id]
            state.update(_pending=None)
            if not revision:
                state["readme"] = _render(project)
            _reset_error(state)
            _message(state, "assistant", "Tell me which part you want to change, or create a draft with the open items." if revision else "No question is active. Name the item you want to defer, for example: Task: unknown.")
            return
        _defer(state, field, text, message_id, pending.get("requirement_id") if not explicit_unknown else None)
        state["_unprocessed"] = [m for m in state.get("_unprocessed", []) if m["message_id"] != message_id]
        _advance(project, reserve, force_draft=was_draft)
        return
    changes, evidence, only_setup = onboarding_setup.extract_message(project, text, current)
    if changes:
        onboarding_setup.update(project, changes, source="chat", evidence=evidence, message_id=message_id)
        if revision:
            for field, setting_fields in onboarding_setup.ITEM_FIELDS.items():
                if any(name in changes for name in setting_fields) and field not in revision["changed_fields"]:
                    revision["changed_fields"].append(field)
    if only_setup:
        state["_unprocessed"] = [m for m in state.get("_unprocessed", []) if m["message_id"] != message_id]
        _message(state, "assistant", "Saved. Your organizer email stays private." if "organizer_email" in changes else "Saved your choice.")
        _advance(project, reserve, force_draft=was_draft)
        return
    if not advisor.configured():
        if revision and current is None and labelled_key not in BY_ID:
            # Do not assign general review feedback to the scientific question.
            _message(state, "assistant", "Rules mode: your feedback is saved for review. Automatic clarification is unavailable.")
            _draft(project, reserve)
            return
        field = current or "question"
        # An explicit checklist label is a routing instruction, not an
        # inferred interpretation of the research content.
        if labelled_key in BY_ID:
            field = labelled_key
        _apply(state, [{"field": field, "status": "partial", "operation": "append", "evidence": [text], "remaining_gap": "Recorded in rules mode. Review this answer against the checklist requirements."}], message_id)
        _rules_method_change(state, field, text)
        onboarding_setup.sync_checklist(project, state)
        state["_unprocessed"] = [m for m in state.get("_unprocessed", []) if m["message_id"] != message_id]
        if field not in state["_asked"]:
            state["_asked"].append(field)
        _message(state, "assistant", "Rules mode: I saved this text under " + BY_ID[field][1] + ". Automatic extraction is unavailable; the answer remains marked for review.")
        _advance(project, reserve, force_draft=was_draft)
        return
    if _call_count(project) >= MAX_CALLS:
        # Preserve the latest message for manual review without pretending it
        # was extracted or dropping it from the final document.
        _draft(project, reserve)
        return
    try:
        context = {"current_message": text, "current_question": state["current_question"], "recorded_items": state["items"],
                   "superseded_evidence": state.get("_superseded_evidence", []),
                   "definition": readiness.DEFINITION, "required_fact_criteria": readiness.REQUIREMENTS,
                   "definition_readiness": readiness.assess(state), "optional_fields": sorted(readiness.OPTIONAL_FIELDS),
                   "criterion_asks": state["_criterion_asks"], "scope_checkpoint": state.get("scope_checkpoint"),
                   "organizer_scope_decisions": readiness.assess(state)["scope_decisions"],
                   "manual_bypasses": readiness.assess(state)["bypasses"],
                   "saved_project_context": _saved_project_context(project),
                   "checklist_requirements": [{"id": key, "label": label, "pillar": pillar, "requirement": gap} for key, label, pillar, _, gap in ITEMS],
                   "already_asked": state["_asked"], "questions_this_round": state["_asked_questions"],
                   "eligible_fields": _eligible(state), "followups_remaining": MAX_FOLLOWUPS - state["followups"],
                   "interview_stages": [{"id": key, "label": label, "fields": fields} for key, label, fields in INTERVIEW_STAGES],
                   "application_owned_items": sorted(AGENT_OWNED_FIELDS),
                   "question_policy": "Clarify the most consequential missing required fact. A field may be revisited with a distinct question when its requirements are incomplete. Do not repeat an unknown answer or a question already asked. A reference baseline is optional. Ask no question for application-owned work.",
                   "previous_user_messages": [m["content"] for m in state["messages"] if m["role"] == "user"][:-1]}
        if revision:
            context.update(revision_context=_revision_context(project), already_asked=[],
                           followups_remaining=MAX_FOLLOWUPS - revision["followups"],
                           questions_this_round=revision["asked_questions"], deferred_this_round=revision["deferred_fields"],
                           question_policy="Clarify the organizer's requested changes and necessary consequences only. The previous interview is context. Ask one targeted question if the change is not yet precise or supported. Do not revisit unrelated old gaps. A checklist field can be clarified again with a distinct question, unless deferred this round. Return empty question fields when the change is ready to draft.")
        parsed, updates, requirements = _validated_response(project, "scope", context, reserve,
                                                            lambda response: _validated_scope(response, text, state))
        _apply(state, updates, message_id)
        if "requirements" in parsed:
            _apply_requirements(state, requirements)
        state["_unprocessed"] = [m for m in state.get("_unprocessed", []) if m["message_id"] != message_id]
        _advance(project, reserve, parsed, force_draft=was_draft)
    except Exception as exc:
        _fail(state, exc, _call_count(project) < MAX_CALLS)


def submit_message(project, text, request_id, reserve=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError("Enter a message of 1 to 12,000 characters.")
    _validate_request_id(request_id)
    state = ensure_conversation(project)
    if request_id in state["_requests"]:
        _request(state, request_id, "message", text.strip())
        return
    if state["status"] == "error" and not _draft_command(text):
        raise ValueError("Retry the unfinished response or create a draft before adding another message.")
    revision = _revision(state)
    start_next_round = bool(revision and revision["status"] == "draft_ready" and not _draft_command(text))
    if start_next_round:
        if len(state["_revision_rounds"]) >= MAX_REVISION_ROUNDS:
            raise ValueError("This challenge has reached its 20-round review limit.")
    if not _request(state, request_id, "message", text.strip()):
        return
    if start_next_round:
        _start_revision(project)
        revision = _revision(state)
    previous_question = state["current_question"] or state.get("scope_checkpoint")
    onboarding_setup.remember_private_mentions(project, text.strip(), previous_question["field"] if previous_question else None)
    _message(state, "user", text.strip())
    if project.get("title") in DEFAULT_TITLES and not _draft_command(text):
        project["title"] = text.strip().splitlines()[0][:80]
        state["_generated_title"] = project["title"]
    if not _draft_command(text):
        state.setdefault("_unprocessed", []).append({"text": text.strip(), "message_id": state["messages"][-1]["id"]})
        if revision:
            key = "clarified_changes" if previous_question else "requested_changes"
            revision[key].append({"text": text.strip(), "message_id": state["messages"][-1]["id"]})
    state["readme"] = None
    state["_draft_meta"] = None
    state["_pending"] = {"kind": "message", "text": text.strip(), "message_id": state["messages"][-1]["id"], "field": previous_question["field"] if previous_question else None,
                         "requirement_id": previous_question.get("requirement_id") if previous_question else None, "was_draft": state["phase"] == "draft"}
    _reset_error(state)
    _process_message(project, reserve)


def skip_question(project, request_id, reserve=None):
    _validate_request_id(request_id)
    state = ensure_conversation(project)
    if request_id in state["_requests"]:
        _request(state, request_id, "skip")
        return
    if state["status"] == "error" or state["current_question"] is None:
        raise ValueError("There is no active question to skip. Retry the response or create a draft.")
    if not _request(state, request_id, "skip"):
        return
    _message(state, "user", "Skip this question.")
    _defer(state, state["current_question"]["field"], "Skip this question.", state["messages"][-1]["id"], state["current_question"].get("requirement_id"))
    _advance(project, reserve)


def make_readme(project, request_id, reserve=None):
    state = ensure_conversation(project)
    if not _request(state, request_id, "draft"):
        return
    _message(state, "user", "Create a draft README.")
    _reset_error(state)
    _draft(project, reserve)


def _advance_after_bypass(project, changed_field, was_active):
    """Refresh the active question without a model call or an automatic draft."""
    state = ensure_conversation(project)
    definition = readiness.assess(state)
    if definition["ready"]:
        state["current_question"] = None
        state["scope_checkpoint"] = None
        if not state.get("readme"):
            state["phase"] = "conversation"
        _message(state, "assistant", "All required details are resolved. Review the recorded scope decisions, then create or review the challenge draft. Application checks remain required.")
        return
    # Preserve an unrelated question and any existing working draft. Removing
    # a bypass from a draft exposes its gap without starting another round.
    if not was_active:
        return
    state["current_question"] = None
    state["scope_checkpoint"] = None
    revision = _revision(state)
    followups = revision["followups"] if revision else state["followups"]
    if followups >= MAX_FOLLOWUPS:
        _message(state, "assistant", "The question limit for this round was reached. Create or review the working draft to see the remaining required details.")
        return
    candidates = _eligible(state)
    if revision:
        candidates = [field for field in candidates if field in revision["changed_fields"]
                      and field not in revision["deferred_fields"]]
    if changed_field in candidates:
        candidates.remove(changed_field)
        candidates.insert(0, changed_field)
    asked = revision["asked_questions"] if revision else state["_asked_questions"]
    for field in candidates:
        for criterion in _open_criteria(state, field):
            text = f"Please define {criterion['label'].lower()} for this challenge. {criterion['description']}"
            if field in readiness.SERVER_FIELDS:
                text = BY_ID[field][3]
            _ask(state, field, criterion, text)
            return
    _message(state, "assistant", "The remaining required details are listed in the checklist. Create or review the working draft to continue from this checkpoint.")


def set_requirement_bypass(project, field, requirement_id, reason, request_id, remove=False, reserve=None):
    """Apply or remove an organizer-authored requirement exception.

    The route must enforce owner access and hold the project lock. Bypasses
    are independent of model-written assessments and never supply facts.
    """
    _validate_request_id(request_id)
    if not isinstance(field, str) or not isinstance(requirement_id, str) or not readiness.can_bypass(field, requirement_id):
        raise ValueError("This requirement cannot be bypassed. Organizer settings and application checks remain required.")
    if type(remove) is not bool:
        raise ValueError("The remove option must be true or false.")
    if not isinstance(reason, str) or len(reason) > readiness.MAX_BYPASS_REASON or (not remove and not reason.strip()):
        raise ValueError("Enter a bypass reason of 1 to 2,000 characters.")
    reason = "" if remove else reason.strip()
    payload = json.dumps([field, requirement_id, reason, remove])
    state = ensure_conversation(project)
    if request_id in state["_requests"]:
        _request(state, request_id, "requirement_bypass", payload)
        return conversation_view(project)
    if state["status"] != "idle" or state.get("_pending") or state.get("_inflight") or state.get("_unprocessed"):
        raise ValueError("Finish or retry the saved response before changing a requirement bypass.")
    item = state["items"][field]
    before = copy.deepcopy(item.get("bypasses", {}).get(requirement_id))
    if remove and before is None:
        raise ValueError("This requirement has no manual bypass to remove.")
    _request(state, request_id, "requirement_bypass", payload)
    timestamp = datetime.now(timezone.utc).isoformat()
    if remove:
        item["bypasses"].pop(requirement_id)
    else:
        onboarding_setup.remember_private_mentions(project, reason)
        item.setdefault("bypasses", {})[requirement_id] = {
            "reason": reason, "created_at": before.get("created_at", timestamp) if before else timestamp,
            "updated_at": timestamp}
    after = copy.deepcopy(item.get("bypasses", {}).get(requirement_id))
    state["_bypass_audit"].append({"field": field, "requirement_id": requirement_id,
                                    "action": "remove" if remove else "update" if before else "add",
                                    "before": before, "after": after, "at": timestamp, "request_id": request_id})
    old_readme = state.get("readme")
    state["_draft_meta"] = None
    _apply_requirements(state, [])
    revision = _revision(state)
    if revision and field not in revision["changed_fields"]:
        revision["changed_fields"].append(field)
    active = state.get("current_question") or state.get("scope_checkpoint")
    was_active = bool((active and active["field"] == field)
                      or (state["phase"] == "initial" and field == "question"))
    if old_readme:
        state["readme"] = _render(project)
    label = next(criterion["label"] for criterion in readiness.REQUIREMENTS[field] if criterion["id"] == requirement_id)
    _message(state, "assistant", f"Manual bypass {'removed' if remove else 'saved'} for {label.lower()}." +
             (" The original answer and evidence are preserved." if remove else " Its reason is recorded in the checklist and challenge draft."))
    # Editing the reason does not change which question is active.
    if before is None or remove:
        _advance_after_bypass(project, field, was_active)
    if reserve:
        reserve(project)
    return conversation_view(project)


def set_scope(project, field, summary, resolutions, request_id, remove=False, reserve=None):
    """Record an organizer's chosen scope without replacing source facts."""
    _validate_request_id(request_id)
    if not isinstance(field, str) or not readiness.can_accept_scope(field):
        raise ValueError("Organizer settings and application checks cannot be accepted through a scope decision.")
    if type(remove) is not bool or not isinstance(summary, str) or not isinstance(resolutions, list):
        raise ValueError("Use a text summary and a list of scope decisions.")
    if (not remove and not 1 <= len(summary.strip()) <= 4000) or len(summary) > 4000:
        raise ValueError("Enter a scope summary of 1 to 4,000 characters.")
    known = {criterion["id"] for criterion in readiness.REQUIREMENTS[field]}
    clean, seen = [], set()
    if len(resolutions) > len(known):
        raise ValueError("Use one decision for each known requirement.")
    for entry in resolutions:
        if not isinstance(entry, dict) or set(entry) != {"requirement_id", "mode", "detail"}:
            raise ValueError("Use a requirement, decision type, and explanation for each scope decision.")
        identifier, mode, detail = entry["requirement_id"], entry["mode"], entry["detail"]
        if identifier not in known or identifier in seen or mode not in readiness.SCOPE_MODES:
            raise ValueError("Use one supported decision for each known requirement.")
        if not isinstance(detail, str) or not 1 <= len(detail.strip()) <= 2000:
            raise ValueError("Explain each decision in 1 to 2,000 characters.")
        if mode == "delegated" and not readiness.can_delegate(field, identifier):
            raise ValueError("This scientific decision cannot be delegated. Confirm it or record an explicit exception.")
        if mode == "confirmed" and (readiness._unknown_only(detail) or (field == "plan" and identifier in {"compute_budget", "token_budget"} and not readiness._budget_amount({"value": detail}))):
            raise ValueError("A confirmed decision needs a concrete answer. Use an exception to record an unresolved assumption.")
        clean.append({"requirement_id": identifier, "mode": mode, "detail": detail.strip()})
        seen.add(identifier)
    if remove and (summary.strip() or resolutions):
        raise ValueError("Remove a scope decision without replacement text.")
    summary = summary.strip()
    payload = json.dumps([field, summary, clean, remove], sort_keys=True)
    state = ensure_conversation(project)
    if request_id in state["_requests"]:
        _request(state, request_id, "scope", payload)
        return conversation_view(project)
    if state["status"] != "idle" or any(state.get(name) for name in ("_pending", "_inflight", "_unprocessed")):
        raise ValueError("Finish or retry the saved response before accepting the scope.")
    item = state["items"][field]
    before = copy.deepcopy(item.get("scope"))
    if remove and not before:
        raise ValueError("This item has no accepted scope to remove.")
    _request(state, request_id, "scope", payload)
    comparable = [{key: record[key] for key in ("requirement_id", "mode", "detail")} for record in (before or {}).get("resolutions", [])]
    if before and not remove and not before.get("stale") and before["summary"] == summary and comparable == clean:
        return conversation_view(project)
    timestamp = datetime.now(timezone.utc).isoformat()
    if remove:
        item.pop("scope", None)
    else:
        onboarding_setup.remember_private_mentions(project, summary)
        for entry in clean:
            onboarding_setup.remember_private_mentions(project, entry["detail"])
            basis = _source_quotes(item.get("requirements", {}).get(entry["requirement_id"], {}))
            entry.update(stale=False, source_evidence=basis, source_version=item.get("_source_version", 0))
            if entry["mode"] == "delegated":
                entry["policy"] = readiness.DELEGATION_POLICIES[(field, entry["requirement_id"])]
        item["scope"] = {"summary": summary, "resolutions": clean, "created_at": (before or {}).get("created_at", timestamp),
                         "updated_at": timestamp, "version": (before or {}).get("version", 0) + 1, "stale": False,
                         "source_evidence": list(dict.fromkeys(quote for record in item.get("requirements", {}).values() for quote in _source_quotes(record))),
                         "source_version": item.get("_source_version", 0)}
    after = copy.deepcopy(item.get("scope"))
    _invalidate_scope_dependents(state, field)
    state["_scope_audit"].append({"field": field, "action": "remove" if remove else "update" if before else "add",
                                 "before": before, "after": after, "at": timestamp, "request_id": request_id})
    active = state.get("current_question") or state.get("scope_checkpoint")
    was_active = bool(active and active["field"] == field) or (state["phase"] == "initial" and field == "question")
    old_readme = state.get("readme")
    state["_draft_meta"] = None
    _apply_requirements(state, [])
    revision = _revision(state)
    if revision and field not in revision["changed_fields"]:
        revision["changed_fields"].append(field)
    if old_readme:
        state["readme"] = _render(project)
    _message(state, "assistant", f"Scope {'removed' if remove else 'saved'} for {BY_ID[field][1].lower()}. The original research statements remain available. Rebuild the package before a new review invitation.")
    _advance_after_bypass(project, field, was_active)
    if remove:
        exhausted = next((criterion for criterion in _open_criteria(state, field)
                          if state["_criterion_asks"].get(field + "." + criterion["id"], 0) >= 2), None)
        if exhausted:
            _checkpoint(state, field, exhausted)
    if reserve:
        reserve(project)
    return conversation_view(project)


def continue_interview(project, request_id, reserve=None):
    """Continue a working draft with a fresh, bounded clarification round."""
    _validate_request_id(request_id)
    state = ensure_conversation(project)
    if request_id in state["_requests"]:
        _request(state, request_id, "continue_interview")
        return
    if state["status"] != "idle" or state.get("_pending") or state.get("_inflight"):
        raise ValueError("Finish or retry the current response before continuing.")
    if _revision(state) or not state.get("readme") or state["phase"] != "draft" or state.get("current_question"):
        raise ValueError("Continue from an interview working draft. Use the revision chat for organizer changes.")
    if readiness.assess(state)["ready"]:
        raise ValueError("The required decisions are already recorded. Build the review package or revise the draft.")
    if state["_interview_round"] >= MAX_REVISION_ROUNDS:
        raise ValueError("The 20-round interview limit was reached. Save the working draft and open issues.")
    _request(state, request_id, "continue_interview")
    state["_interview_round"] += 1
    state["_interview_call_start"] = project.get("_model_calls", 0)
    state.update(followups=0, _asked=[], _asked_questions=[], current_question=None, phase="conversation")
    state["_requirements_assessed"] = True
    # Explicit unknowns stay open without being asked again. The researcher
    # can supply a correction when the missing information becomes available.
    _message(state, "assistant", "Let's resolve the remaining required details. Unknown answers stay open. The reference baseline is optional.")
    _advance(project, reserve)
    if reserve:
        reserve(project)


def retry_turn(project, request_id, reserve=None):
    _validate_request_id(request_id)
    state = ensure_conversation(project)
    if request_id in state["_requests"]:
        _request(state, request_id, "retry")
        return
    if _call_count(project) >= MAX_CALLS:
        raise ValueError("The 12-call model limit has been reached. Create a draft from the saved answers.")
    if state["status"] != "error" or not state["can_retry"] or not state.get("_pending"):
        raise ValueError("There is no failed response to retry.")
    if not _request(state, request_id, "retry"):
        return
    _reset_error(state)
    if state["_pending"]["kind"] == "draft":
        _draft(project, reserve)
    else:
        _process_message(project, reserve)
