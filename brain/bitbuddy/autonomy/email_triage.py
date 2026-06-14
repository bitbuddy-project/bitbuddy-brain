"""Email triage: read-only "connect the dots" pass over unread mail.

On wake BitBuddy looks at the inbox and asks the model which one or two unread
messages genuinely need the user's decision — not just a count, but a judgment.
Only subject + sender + the snippet already present on each message are sent to
the provider; full bodies are never read here (lower latency, less leaves the
machine for cloud providers, and the chat model can pull the full body later via
`email_read_message` only if the user says "yes, deal with it"). Any failure
returns an empty list so the caller falls back to the legacy count brief.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..config import load_config
from .decision import collect_model_text, extract_json_object
from .log import log_autonomy

# How many unread messages to show the model, and how many to keep after triage.
MAX_TRIAGE_CANDIDATES = 12
MAX_TRIAGE_ITEMS = 2
# Only surface messages the model scores at or above this importance (1-5).
MIN_TRIAGE_IMPORTANCE = 4
VALID_ACTIONS = {"calendar", "reminder", "task", "trash"}


@dataclass(frozen=True)
class TriagedEmail:
    message_id: str
    mailbox: str
    subject: str
    sender: str
    importance: int
    one_line: str
    suggested_actions: list[str] = field(default_factory=list)
    due_hint: str = ""


def _is_unread(message) -> bool:
    flags = [str(flag).lower() for flag in getattr(message, "flags", []) or []]
    return not any("seen" in flag for flag in flags)


def _sender_label(message) -> str:
    raw = str(getattr(message, "from_addr", "") or "").strip()
    if "<" in raw and ">" in raw:
        name = raw.split("<", 1)[0].strip().strip('"')
        if name:
            return name
    return raw or "unknown sender"


TRIAGE_SYSTEM_PROMPT = (
    "You are BitBuddy, a present, protective companion triaging the user's unread email. "
    "Most email is noise. Pick ONLY the one or two messages that genuinely need the user's "
    "decision or action soon (a reply they must make, a deadline, a bill, a meeting, a person "
    "waiting on them). Ignore newsletters, receipts, marketing, and FYI notices. "
    "For each chosen message suggest concrete next actions from this fixed set only: "
    "'calendar' (add a date/event), 'reminder' (nudge them later), 'task' (save as a to-do), "
    "'trash' (it's noise, filter the sender). "
    "Respond with a single JSON object: "
    '{"important": [{"message_id": "...", "importance": 1-5, "needs_decision": true|false, '
    '"one_line": "what it needs, in one short sentence", '
    '"suggested_actions": ["calendar"|"reminder"|"task"|"trash"], "due_hint": "optional, e.g. Friday"}]}. '
    "Use message_id values exactly as given. If nothing truly needs the user, return "
    '{"important": []}. No prose outside the JSON.'
)


def _build_triage_messages(catalog: list[dict]) -> list[dict]:
    lines = []
    for entry in catalog:
        lines.append(
            f"- message_id: {entry['message_id']}\n"
            f"  from: {entry['sender']}\n"
            f"  subject: {entry['subject']}\n"
            f"  snippet: {entry['snippet']}"
        )
    return [
        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
        {"role": "user", "content": "Unread messages:\n" + "\n".join(lines)},
    ]


def triage_unread(client, *, limit: int = 25, model: str | None = None) -> list[TriagedEmail]:
    """Return the unread messages that genuinely need the user, or [] on anything unclear."""
    config = load_config().email
    if not config.enabled:
        return []
    try:
        from ..email.service import list_messages
    except Exception as error:
        log_autonomy("email_triage_skip", "Email service unavailable for triage", {"error": str(error)})
        return []
    try:
        messages = list_messages(mailbox=config.default_mailbox or "INBOX", limit=limit, enforce=False)
    except Exception as error:
        log_autonomy("email_triage_skip", "Could not read inbox for triage", {"error": str(error)})
        return []

    unread = [message for message in messages if _is_unread(message)]
    if not unread:
        return []

    default_mailbox = config.default_mailbox or "INBOX"
    catalog: dict[str, dict] = {}
    for message in unread[:MAX_TRIAGE_CANDIDATES]:
        message_id = str(getattr(message, "id", "") or "").strip()
        if not message_id:
            continue
        catalog[message_id] = {
            "message_id": message_id,
            "mailbox": str(getattr(message, "mailbox", "") or "") or default_mailbox,
            "subject": str(getattr(message, "subject", "") or "(no subject)").strip()[:200],
            "sender": _sender_label(message),
            "snippet": str(getattr(message, "snippet", "") or "").strip()[:280],
        }
    if not catalog:
        return []

    try:
        raw = collect_model_text(client, _build_triage_messages(list(catalog.values())), model=model)
        data = json.loads(extract_json_object(raw))
    except Exception as error:
        log_autonomy("email_triage_skip", "Triage model pass failed", {"error": str(error)})
        return []

    results: list[TriagedEmail] = []
    for entry in data.get("important") or []:
        if not isinstance(entry, dict):
            continue
        message_id = str(entry.get("message_id") or "").strip()
        source = catalog.get(message_id)
        if source is None:  # ignore hallucinated ids; trust our own handle data
            continue
        if not entry.get("needs_decision"):
            continue
        try:
            importance = int(entry.get("importance") or 0)
        except (TypeError, ValueError):
            importance = 0
        if importance < MIN_TRIAGE_IMPORTANCE:
            continue
        actions = [str(a).strip().lower() for a in (entry.get("suggested_actions") or [])]
        actions = [a for a in actions if a in VALID_ACTIONS]
        results.append(
            TriagedEmail(
                message_id=message_id,
                mailbox=source["mailbox"],
                subject=source["subject"],
                sender=source["sender"],
                importance=importance,
                one_line=str(entry.get("one_line") or "").strip()[:240],
                suggested_actions=actions,
                due_hint=str(entry.get("due_hint") or "").strip()[:80],
            )
        )
        if len(results) >= MAX_TRIAGE_ITEMS:
            break
    return results
