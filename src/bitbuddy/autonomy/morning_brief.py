"""Morning email brief.

When BitBuddy wakes for the day she takes a quick, read-only look at email. First
she tries to *connect the dots*: a model triage pass picks the one or two unread
messages that genuinely need the user and surfaces each as a question with a
concrete action menu (add to calendar, remind me, save as a task, or filter the
sender). If triage finds nothing — or the provider is unavailable — she falls
back to a single quiet brief comment, and if the inbox is quiet she stays silent.
Delivery rides the normal intention pipeline (so cadence, cooldown, and
quiet-hours guards all apply); this module only decides whether to queue.
"""

from __future__ import annotations

from ..config import load_config
from ..providers import ProviderClient
from .email_triage import TriagedEmail, _is_unread, _sender_label, triage_unread
from .intentions import create_intention, has_intention_with_metadata
from .log import log_autonomy

# Re-brief at most once per this many hours so a flapping wake state can't spam.
MORNING_BRIEF_INTERVAL_HOURS = 18
MAX_BRIEF_ITEMS = 3
# Triage questions outrank the plain count comment so important mail surfaces promptly.
TRIAGE_PRIORITY = 5


def build_morning_brief_content() -> str:
    """Return a brief comment about useful unread email, or '' when nothing is worth saying."""
    config = load_config().email
    if not config.enabled:
        return ""
    try:
        from ..email.service import list_messages
    except Exception as error:
        log_autonomy("morning_brief_skip", "Email service unavailable for morning brief", {"error": str(error)})
        return ""
    try:
        messages = list_messages(mailbox=config.default_mailbox or "INBOX", limit=25, enforce=False)
    except Exception as error:
        log_autonomy("morning_brief_skip", "Could not read inbox for morning brief", {"error": str(error)})
        return ""

    unread = [message for message in messages if _is_unread(message)]
    if not unread:
        return ""

    highlights = []
    for message in unread[:MAX_BRIEF_ITEMS]:
        subject = str(getattr(message, "subject", "") or "(no subject)").strip()[:120]
        highlights.append(f"“{subject}” from {_sender_label(message)}")
    more = len(unread) - len(highlights)
    tail = f", plus {more} more" if more > 0 else ""
    items = "; ".join(highlights)
    return f"Morning. You have {len(unread)} unread email(s): {items}{tail}."


def _action_menu_phrase(actions: list[str]) -> str:
    labels = {
        "calendar": "add it to your calendar",
        "reminder": "set a reminder",
        "task": "save it as a task",
        "trash": "filter that sender",
    }
    chosen = [labels[action] for action in actions if action in labels]
    if not chosen:
        chosen = [labels["calendar"], labels["reminder"], labels["task"]]
    has_trash = "filter that sender" in chosen
    actiony = [phrase for phrase in chosen if phrase != "filter that sender"]
    if actiony:
        joined = actiony[0] if len(actiony) == 1 else ", ".join(actiony[:-1]) + ", or " + actiony[-1]
        ask = f"Want me to {joined}?"
    else:
        ask = "Want me to handle it?"
    if has_trash:
        ask += " Or say it's noise and I'll filter that sender."
    return ask


def _triage_question_content(item: TriagedEmail) -> str:
    due = f" (due {item.due_hint})" if item.due_hint else ""
    summary = item.one_line or f"“{item.subject}” from {item.sender} looks like it needs you"
    if item.subject.lower() not in summary.lower():
        summary = f"“{item.subject}” from {item.sender} — {summary}"
    return f"Heads up — {summary}{due}. {_action_menu_phrase(item.suggested_actions)}"


def _queue_triage_question(item: TriagedEmail) -> object | None:
    content = _triage_question_content(item)
    try:
        return create_intention(
            "question",
            content,
            f"Important email from {item.sender}: {item.subject}",
            metadata={
                "source_activity": "email_triage",
                "priority": TRIAGE_PRIORITY,
                "email": {
                    "message_id": item.message_id,
                    "mailbox": item.mailbox,
                    "subject": item.subject,
                    "sender": item.sender,
                    "suggested_actions": item.suggested_actions,
                    "due_hint": item.due_hint,
                },
                "quality": {"accepted": True, "importance": TRIAGE_PRIORITY, "source_activity": "email_triage"},
            },
        )
    except ValueError:
        return None


def queue_morning_brief(client: object | None = None) -> object | None:
    """Queue an email-triage question (or a fallback brief comment) if useful; else stay silent."""
    config = load_config().email
    if not getattr(config, "enabled", False):
        return None
    # One brief per window, whether it came through triage or the fallback count.
    if has_intention_with_metadata(source_activity="email_triage", within_hours=MORNING_BRIEF_INTERVAL_HOURS) or \
            has_intention_with_metadata(source_activity="morning_brief", within_hours=MORNING_BRIEF_INTERVAL_HOURS):
        return None

    triaged: list[TriagedEmail] = []
    try:
        triage_client = client or ProviderClient(load_config().provider)
        triaged = triage_unread(triage_client)
    except Exception as error:
        log_autonomy("email_triage_skip", "Email triage unavailable; using fallback brief", {"error": str(error)})

    if triaged:
        queued = [intention for item in triaged if (intention := _queue_triage_question(item)) is not None]
        if queued:
            log_autonomy(
                "email_triage_queued",
                f"Surfaced {len(queued)} important email(s) as questions",
                {"intention_ids": [getattr(intention, "id", None) for intention in queued]},
            )
            return queued[0]

    content = build_morning_brief_content()
    if not content:
        return None
    try:
        intention = create_intention(
            "comment",
            content,
            "Morning email brief",
            metadata={
                "source_activity": "morning_brief",
                "priority": 4,
                "quality": {"accepted": True, "importance": 4, "source_activity": "morning_brief"},
            },
        )
    except ValueError:
        return None
    log_autonomy("morning_brief_queued", "Queued a morning email brief", {"intention_id": intention.id})
    return intention
