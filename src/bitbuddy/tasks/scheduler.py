"""Time-based reminder scheduler for user tasks.

The idle autonomy loop only runs while the user is away, so it cannot deliver
time-precise reminders. This lightweight daemon timer wakes on a fixed cadence,
finds tasks whose ``remind_at`` has come due, de-dupes via ``reminded_at``, and
fires a toast notification (no chat message). The cadence/dedup structure mirrors
``bitbuddy.calendar.scheduler``.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone

from ..config import load_config
from ..notifications import notify_user
from . import store

_TIMER_LOCK = threading.Lock()
_TIMER: threading.Timer | None = None


def start_task_scheduler() -> None:
    _schedule_next(_tick_seconds(), initial=True)


def _tick_seconds() -> int:
    try:
        return int(load_config().calendar.scheduler_tick_seconds)
    except Exception:
        return 60


def _schedule_next(delay_seconds: int, *, initial: bool = False) -> None:
    delay = max(15, int(delay_seconds))
    timer = threading.Timer(delay, run_task_tick)
    timer.daemon = True
    with _TIMER_LOCK:
        global _TIMER
        if _TIMER is not None and not initial:
            _TIMER.cancel()
        _TIMER = timer
        timer.start()


def run_task_tick() -> None:
    try:
        _process_due_tasks()
    except Exception as error:  # never let a tick kill the timer
        print(f"BitBuddy task scheduler tick failed: {error}", file=sys.stderr)
    finally:
        _schedule_next(_tick_seconds())


def _process_due_tasks() -> None:
    tz = ""
    try:
        tz = load_config().user_context.timezone or ""
    except Exception:
        tz = ""
    for task in store.due_tasks_to_fire(datetime.now(timezone.utc)):
        store.mark_task_reminded(task.id)
        _fire(task, tz)


def _fire(task: store.Task, tz: str) -> None:
    # Reminders surface as a toast notification only — they deliberately do NOT
    # post into chat. Clicking the toast opens the main chat.
    when = _local_label(task.remind_at, tz) if task.remind_at else ""
    title = f"Reminder: {task.title}"
    body = task.notes or (f"Reminder you set{f' for {when}' if when else ''}: {task.title}.")

    notify_user(
        category="reminder",
        severity="warning" if task.priority >= 4 else "info",
        title=title,
        body=body,
        source_kind="task",
        action_url="/",
        metadata={"task_id": task.id, "task_remind_at": task.remind_at, "task_priority": task.priority},
    )


def _local_label(iso: str, tz: str) -> str:
    from ..calendar.store import local_label

    return local_label(iso, tz)
