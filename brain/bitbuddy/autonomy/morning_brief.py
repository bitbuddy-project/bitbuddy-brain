"""Morning email brief.

When BitBuddy wakes for the day she takes a quick, read-only look at email and — only
if something genuinely useful is waiting — queues a single brief comment. If the inbox
is quiet she stays silent. Delivery rides the normal intention pipeline (so cadence,
cooldown, and quiet-hours guards all apply); this module only decides whether to queue.
"""

from __future__ import annotations

from ..config import load_config
from .intentions import create_intention, has_intention_with_metadata
from .log import log_autonomy

# Re-brief at most once per this many hours so a flapping wake state can't spam.
MORNING_BRIEF_INTERVAL_HOURS = 18
MAX_BRIEF_ITEMS = 3


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


def queue_morning_brief() -> object | None:
    """Queue a single morning-brief intention if there is useful email; else stay silent."""
    if has_intention_with_metadata(source_activity="morning_brief", within_hours=MORNING_BRIEF_INTERVAL_HOURS):
        return None
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
