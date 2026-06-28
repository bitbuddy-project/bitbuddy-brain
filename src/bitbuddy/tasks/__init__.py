"""User-facing tasks and reminders.

Unlike ``self_notes`` (which passively inject into chat context) or the autonomy
``intentions`` (BitBuddy's own thoughts surfaced on idle), these are tasks the
*user* asks BitBuddy to remember. A task may carry a ``remind_at`` time; the
:mod:`bitbuddy.tasks.scheduler` daemon fires a notification + chat nudge when it
comes due, reusing the same firing pattern as the calendar scheduler.
"""

from .store import (
    Task,
    complete_task,
    create_task,
    delete_task,
    due_tasks_to_fire,
    get_task,
    list_tasks,
    mark_task_reminded,
    task_to_json,
    update_task,
)

__all__ = [
    "Task",
    "complete_task",
    "create_task",
    "delete_task",
    "due_tasks_to_fire",
    "get_task",
    "list_tasks",
    "mark_task_reminded",
    "task_to_json",
    "update_task",
]
