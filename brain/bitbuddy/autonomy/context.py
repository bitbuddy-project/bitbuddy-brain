from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..activity import list_activity
from ..config import load_config
from ..continuity import build_continuity_digest
from ..lifecycle import lifecycle_status
from ..memory.project import list_projects, project_model
from ..self_model import goal_task_state, list_goals
from ..self_notes import select_self_notes_for_context
from ..workspace import latest_document_for_goal
from .intentions import list_pending_intentions


def build_autonomy_context(chat_id: str, consolidation_result: dict[str, object] | None = None) -> str:
    config = load_config()
    timezone = config.user_context.timezone or "UTC"
    now = datetime.now(ZoneInfo(timezone))
    lines = [
        "[Safe Idle Autonomy Context]",
        "Autonomy is safe by construction: only non-destructive built-in capabilities are available.",
        "This cycle may run exactly one activity and then stop.",
        f"Chat id: {chat_id}",
        f"Local time: {now.isoformat()} ({timezone})",
        f"Pending intentions: {len(list_pending_intentions(limit=50))}",
        f"Lifecycle: {lifecycle_status().get('state')} quiet_mode={lifecycle_status().get('quiet_mode')}",
        "",
        "[Available Fixed Activities]",
        "- web_curiosity: search SearxNG, reflect, optionally remember or queue a later thought.",
        "- project_familiarization: read already-registered project files only and update project memory.",
        "- generate_user_prompts: create only high-signal questions/comments for the future intention queue; skip if nothing is genuinely worth surfacing.",
        "- self_reflection: update BitBuddy's self-state, goals, desire for bounded freedom, or emergent personality from grounded evidence.",
        "- pursue_goal: safely advance BitBuddy's own autonomy-allowed goals and leave useful notes in AI Space.",
        "- network_observation: currently not implemented; execution will skip safely.",
        "- do_nothing: stop without action.",
        "",
    ]
    if consolidation_result:
        lines.extend(["[Recent Memory Consolidation Result]", str(consolidation_result)[:3000], ""])
    continuity = build_continuity_digest(
        chat_id=chat_id,
        latest_user_text=str(consolidation_result or ""),
        source="autonomy",
        max_chars=2200,
    )
    if continuity:
        lines.extend([continuity, ""])
    if config.dreaming.self_note_injection_enabled:
        notes = select_self_notes_for_context(query=str(consolidation_result or ""), limit=3, mark_injected=True)
        if notes:
            lines.extend(["[Relevant SelfNotes]"])
            for note in notes:
                lines.append(f"- {note.kind} priority={note.priority}: {note.text}")
            lines.append("")
    projects = list_projects()
    lines.append("[Registered Projects]")
    if not projects:
        lines.append("No registered projects.")
    for project in projects[:12]:
        summary = project_model(project.id, limit=5)
        card = summary.get("project_card") if isinstance(summary.get("project_card"), dict) else {}
        lines.append(f"- {project.name} | {project.id} | paths={', '.join(str(path) for path in project.paths)}")
        if card.get("purpose"):
            lines.append(f"  purpose: {card.get('purpose')}")
        if card.get("current_status"):
            lines.append(f"  status: {card.get('current_status')}")
    actionable_goals = [
        goal for goal in list_goals(include_done=False, limit=12)
        if goal.status == "active" and goal.autonomy_allowed and goal.risk_level <= 1 and goal.next_action.strip()
    ]

    in_progress = [
        (goal, goal_task_state(goal))
        for goal in actionable_goals
        if goal_task_state(goal).get("status") == "in_progress"
    ]
    if in_progress:
        lines.extend(["", "[In-Progress Task — resume this, do not restart]"])
        for goal, state in in_progress[:3]:
            plan = state.get("plan") if isinstance(state.get("plan"), list) else []
            step_index = int(state.get("step_index") or 0)
            current_step = plan[step_index] if 0 <= step_index < len(plan) else (goal.next_action or "continue")
            lines.append(f"- goal {goal.id}: {goal.title}")
            lines.append(f"  on step {step_index + 1}/{max(len(plan), step_index + 1)}: {current_step}")
        lines.append("Choose pursue_goal on the in-progress goal to finish what you already started, unless it is blocked.")

    lines.extend(["", "[Active Self-Goals]"])
    if not actionable_goals:
        lines.append("No autonomy-allowed goals with a concrete next action.")
    for goal in actionable_goals[:6]:
        state = goal_task_state(goal)
        lines.append(f"- goal {goal.id}: {goal.title}")
        lines.append(f"  next_action: {goal.next_action}")
        if state.get("status"):
            task_line = f"  task: {state.get('status')}"
            if state.get("status") == "blocked" and state.get("blocked_reason"):
                task_line += f" — {state.get('blocked_reason')}"
            lines.append(task_line)
        latest = latest_document_for_goal(str(goal.id))
        if latest is not None:
            lines.append(f"  recent progress: \"{latest.title}\" ({latest.kind}, updated {latest.updated_at})")
    lines.extend(["", "[Recent Activity]"])
    for item in list_activity(limit=12):
        lines.append(f"- {item['created_at']} {item['kind']}: {item['message']}")
    return "\n".join(lines)
