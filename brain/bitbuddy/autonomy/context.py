from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..activity import list_activity
from ..config import load_config
from ..continuity import build_continuity_digest
from ..lifecycle import lifecycle_status
from ..memory.project import list_projects, project_model
from ..self_notes import select_self_notes_for_context
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
        "- generate_user_prompts: create questions/comments for the future intention queue.",
        "- self_reflection: update BitBuddy's self-state, goals, or emergent personality from grounded evidence.",
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
    lines.extend(["", "[Recent Activity]"])
    for item in list_activity(limit=12):
        lines.append(f"- {item['created_at']} {item['kind']}: {item['message']}")
    return "\n".join(lines)
