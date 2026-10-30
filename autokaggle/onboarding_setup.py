"""Validated organizer choices, kept separate from model-written answers."""
from __future__ import annotations

import copy
import html
import json
import re
import uuid


ITEM_FIELDS = {"competition": ("competition_type",),
               "submissions": ("daily_submission_limit", "submissions_confirmed"),
               "organizer": ("organizer_email",)}
LABELS = {"competition": "competition", "competition type": "competition",
          "submissions": "submissions", "daily submissions": "submissions",
          "organizer": "organizer", "organizer email": "organizer"}
NUMBER_WORDS = {word: number for number, word in enumerate(
    ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), 1)}
QUOTA_NUMBER = r"(?:\d+|" + "|".join(NUMBER_WORDS) + r")"
CHOICE_PREFIX = r"(?:(?:we |i )?(?:choose|select|want|prefer|use)|let['’]s use)\s+(?:a |an )?"


def defaults():
    return {"competition_type": None, "daily_submission_limit": 5,
            "submissions_confirmed": False, "organizer_email": ""}


def validate_email(value):
    """Accept one ordinary mailbox address, not a display name or mail header."""
    if not isinstance(value, str):
        raise ValueError("Organizer email must be text.")
    if "\r" in value or "\n" in value:
        raise ValueError("Enter one valid organizer email address.")
    value = value.strip()
    if not value:
        return ""
    if len(value) > 254 or value.count("@") != 1:
        raise ValueError("Enter one valid organizer email address.")
    local, domain = value.rsplit("@", 1)
    if (not local or len(local) > 64 or local.startswith(".") or local.endswith(".")
            or ".." in local or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)):
        raise ValueError("Enter one valid organizer email address.")
    labels = domain.split(".")
    if len(labels) < 2 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
        raise ValueError("Enter one valid organizer email address.")
    return local + "@" + domain.lower()


def validate_changes(changes):
    if not isinstance(changes, dict) or any(key not in defaults() for key in changes):
        raise ValueError("Use only the supported organizer setup fields.")
    result = copy.deepcopy(changes)
    if "competition_type" in result and result["competition_type"] not in (None, "prediction", "code"):
        raise ValueError("Choose prediction or code as the competition type.")
    if "daily_submission_limit" in result:
        limit = result["daily_submission_limit"]
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Daily submissions must be a whole number from 1 to 1,000.")
    if "submissions_confirmed" in result and type(result["submissions_confirmed"]) is not bool:
        raise ValueError("Submission confirmation must be true or false.")
    if "organizer_email" in result:
        result["organizer_email"] = validate_email(result["organizer_email"])
    return result


def get(project, include_private=True):
    """Migrate missing fields and return a copy. Email is owner-only by default."""
    stored = project.get("setup")
    result = defaults()
    if isinstance(stored, dict):
        for key in result:
            if key in stored:
                try:
                    result.update(validate_changes({key: stored[key]}))
                except ValueError:
                    if key == "daily_submission_limit":
                        result["submissions_confirmed"] = False
        if type(stored.get("daily_submission_limit", 5)) is not int or not 1 <= stored.get("daily_submission_limit", 5) <= 1000:
            result["submissions_confirmed"] = False
    project["setup"] = result
    visible = copy.deepcopy(result)
    if not include_private:
        visible.pop("organizer_email")
    return visible


def sync_checklist(project, state):
    """Make the three checklist items agree with validated organizer choices."""
    values = get(project)
    display = {
        "competition": (values["competition_type"] is not None,
                        {"prediction": "Prediction competition: participants submit predictions for supplied test inputs.",
                         "code": "Code competition: submitted code runs against hidden test inputs."}.get(values["competition_type"], ""),
                        "Choose prediction submissions or code submissions explicitly."),
        "submissions": (values["submissions_confirmed"],
                        f"{values['daily_submission_limit']} submissions per day" + (" (confirmed)." if values["submissions_confirmed"] else " (default or proposed; not confirmed)."),
                        f"Confirm {values['daily_submission_limit']} submissions per day, or choose another limit."),
        "organizer": (bool(values["organizer_email"]), values["organizer_email"],
                      "Provide the organizer email for private draft review."),
    }
    for key, (complete, value, gap) in display.items():
        item = state["items"].get(key)
        if item is None:
            continue
        item["value"] = value
        if complete:
            item.update(status="answered", gap="")
        else:
            if item["status"] == "answered":
                item["status"] = "missing"
            item["gap"] = gap
    active = state.get("current_question")
    if active and active["field"] in ITEM_FIELDS and state["items"][active["field"]]["status"] == "answered":
        state["current_question"] = None


def update(project, changes, *, source="form", evidence=None, message_id=None):
    """Validate atomically, record source evidence, and invalidate stale drafts.

    A quota change needs explicit ``submissions_confirmed: true``. Form callers
    need only pass project and changes. Chat callers can supply source excerpts.
    """
    clean = validate_changes(changes)
    previous = get(project)
    updated = {**previous, **clean}
    if "daily_submission_limit" in clean and clean["daily_submission_limit"] != previous["daily_submission_limit"] and "submissions_confirmed" not in clean:
        updated["submissions_confirmed"] = False
    from .conversation import ensure_conversation
    state = ensure_conversation(project)
    if not clean:
        return get(project)
    before = {key: copy.deepcopy(state["items"][key]) for key in ITEM_FIELDS}
    project["setup"] = updated
    addresses = project.setdefault("_setup_private_emails", [])
    for address in (previous["organizer_email"], updated["organizer_email"]):
        if address and address not in addresses:
            addresses.append(address)
    reference = message_id or "setup:" + str(uuid.uuid4())
    for key, fields in ITEM_FIELDS.items():
        if not any(field in clean for field in fields):
            continue
        quotes = list((evidence or {}).get(key, []))
        if not quotes:
            quotes = [json.dumps({field: clean[field] for field in fields if field in clean}, sort_keys=True)]
        state["items"][key]["evidence"].append({"message_id": reference, "source": source, "quotes": quotes})
        state["_history"].append({"field": key, "before": before[key], "message_id": reference,
                                  "operation": "setup", "source": source, "replacement_evidence": quotes})
    sync_checklist(project, state)
    if updated != previous:
        state["readme"] = None
        state["_draft_meta"] = None
    return get(project)


def evidence_patch(field, evidence):
    """Parse only explicit setup choices; a model cannot invent confirmation."""
    text = "\n".join(evidence).strip()
    text = re.sub(r"^(?:competition(?: type)?|daily submissions|submissions|organizer(?: email)?)\s*:\s*", "", text, flags=re.IGNORECASE)
    if field == "competition":
        match = re.fullmatch(r"(?:" + CHOICE_PREFIX + r")?(prediction|code)(?:\s+(?:competition|submissions?|file))?[.!]?", text, re.IGNORECASE)
        return {"competition_type": match[1].lower()} if match else None
    if field == "submissions":
        match = re.fullmatch(r"(?:(?:we |i )?(?:confirm|choose|allow|use|set|keep)\s+)?(" + QUOTA_NUMBER
                             + r")(?:\s+submissions?)?(?:\s+per\s+team)?(?:\s+(?:per|a|each)\s+(?:UTC\s+)?day|\s*/\s*day)?[.!]?", text, re.IGNORECASE)
        if match:
            value = NUMBER_WORDS.get(match[1].lower()) if not match[1].isdigit() else int(match[1])
            if value is not None and 1 <= value <= 1000:
                return {"daily_submission_limit": value, "submissions_confirmed": True}
        return None
    if field == "organizer":
        try:
            # Chat can end a sentence after an address. The settings form
            # still validates its entire value without this normalization.
            email = validate_email(text.rstrip(".,;!"))
        except ValueError:
            return None
        return {"organizer_email": email} if email else None
    return None


def remember_private_mentions(project, text, current_field=None):
    """Keep organizer addresses private even when a chat answer needs review."""
    if not isinstance(text, str):
        return
    organizer_context = current_field == "organizer" or re.search(r"\b(?:organizer(?:[’']s)?(?:\s+email)?|(?:my|our)\s+(?:review\s+)?email)\b", text, re.IGNORECASE)
    if not organizer_context and not evidence_patch("organizer", [text]):
        return
    candidates = re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", text)
    for candidate in candidates:
        try:
            address = validate_email(candidate.rstrip("."))
        except ValueError:
            continue
        if address:
            known = project.setdefault("_setup_private_emails", [])
            if address not in known:
                known.append(address)


def extract_message(project, text, current_field=None):
    """Read explicit settings without asking a model to infer organizer intent.

    Return a patch, original source excerpts, and whether the whole message is
    setup input. Mixed research prose still goes through the scoping step.
    """
    remember_private_mentions(project, text, current_field)
    if current_field in ITEM_FIELDS:
        direct = evidence_patch(current_field, [text])
        if current_field == "submissions" and text.strip().lower().rstrip(".!?") in {"yes", "yes please", "confirmed", "confirm", "keep the default", "use the default"}:
            direct = {"daily_submission_limit": get(project)["daily_submission_limit"], "submissions_confirmed": True}
        if direct:
            return direct, {current_field: [text]}, True
    chunks = [part.strip() for part in re.split(r"\n+|(?<=[.!?])\s+", text) if part.strip()]
    found, evidence, unhandled, conflicts = {}, {}, False, set()
    for chunk in chunks:
        # Accept a complete, explicit combined choice. Match the full sentence
        # so alternatives, conditions, negation, and trailing uncertainty do
        # not silently confirm either setting.
        combined = re.fullmatch(
            r"(" + CHOICE_PREFIX + r"(?:prediction|code)\s+(?:competition|submissions?|file))"
            r"\s*(?:,|and)\s*((?:keep |allow |use |confirm )?" + QUOTA_NUMBER + r"(?:\s+submissions?)?\s+(?:per\s+team\s+)?per\s+(?:UTC\s+)?day)[.!]?", chunk, re.IGNORECASE)
        if combined:
            entries = [(key, evidence_patch(key, [combined[index]])) for key, index in (("competition", 1), ("submissions", 2))]
            if all(patch for _, patch in entries):
                for key, patch in entries:
                    if any(name in found and found[name] != value for name, value in patch.items()):
                        conflicts.add(key)
                        unhandled = True
                    else:
                        found.update(patch)
                        evidence.setdefault(key, []).append(chunk)
                continue
        labelled = re.match(r"^([A-Za-z ]+)\s*:\s*(.+)$", chunk)
        key = LABELS.get(labelled[1].strip().lower()) if labelled else None
        patch = evidence_patch(key, [labelled[2]]) if key else None
        if not key:
            # Unlabelled settings need an explicit selection sentence. Bare
            # numbers in research prose are never treated as a quota.
            if re.match(r"^(?:" + CHOICE_PREFIX + r"|(?:prediction|code)(?:\s+(?:competition|submissions?|file))?[.!]?$)", chunk, re.IGNORECASE):
                patch = evidence_patch("competition", [chunk])
                if patch:
                    key = "competition"
            if not patch and re.match(r"^(?:we |i )?(?:confirm|choose|allow|use|set|keep)\s+" + QUOTA_NUMBER + r"\b", chunk, re.IGNORECASE):
                patch = evidence_patch("submissions", [chunk])
                if patch:
                    key = "submissions"
            organizer = re.fullmatch(r"(?:(?:the |our |my )?organizer(?:[’']s)?\s+|(?:my|our)\s+)(?:review\s+)?email\s+is\s+(.+)", chunk, re.IGNORECASE)
            if not patch and organizer:
                patch = evidence_patch("organizer", [organizer[1]])
                if patch:
                    key = "organizer"
            if not patch and len(chunks) == 1:
                patch = evidence_patch("organizer", [chunk])
                if patch:
                    key = "organizer"
        if not patch:
            unhandled = True
            continue
        if any(name in found and found[name] != value for name, value in patch.items()):
            conflicts.add(key)
            unhandled = True
            continue
        found.update(patch)
        evidence.setdefault(key, []).append(chunk)
    for key in conflicts:
        for field in ITEM_FIELDS[key]:
            found.pop(field, None)
        evidence.pop(key, None)
    return found, evidence, bool(found) and not unhandled


def redact_private(project, text):
    """Remove current and historical organizer addresses from public text."""
    addresses = set(project.get("_setup_private_emails", []))
    address = get(project)["organizer_email"]
    if address:
        addresses.add(address)
    result = str(text)
    for address in sorted(addresses, key=len, reverse=True):
        for form in {address, html.escape(address)}:
            result = re.sub(re.escape(form), "[private organizer email]", result, flags=re.IGNORECASE)
    return result
