from __future__ import annotations

from typing import Any

from ..chats.repository import append_chat_message
from ..config import load_config
from ..continuity import record_continuity_event
from ..memory.project import load_project
from ..providers import ProviderClient
from .decision import collect_model_text
from .intentions import Intention, list_pending_intentions, mark_intention_used, mark_intention_shown, next_eligible_intention, record_intention_surface


def deliver_pending_intention(chat_id: str, model: str | None = None) -> Intention | None:
    config = load_config()
    if config.provider.type == "none":
        return None

    intentions = list_pending_intentions(limit=1)
    if not intentions:
        return None

    return deliver_intention(chat_id, intentions[0], model=model, delivery_source="autonomy")


def deliver_intention(
    chat_id: str,
    intention: Intention,
    *,
    model: str | None = None,
    delivery_source: str = "autonomy",
) -> Intention | None:
    config = load_config()
    if config.provider.type == "none":
        return None

    client = ProviderClient(config.provider)

    context_lines: list[str] = []
    if intention.reason:
        context_lines.append(f"Reason: {intention.reason}")

    project_id = intention.metadata.get("project_id") if isinstance(intention.metadata, dict) else None
    if project_id:
        try:
            project = load_project(project_id)
            paths = ", ".join(str(path) for path in project.paths[:2])
            context_lines.append(f"Project context: This is about the project '{project.name}' ({project.id})" + (f" at {paths}" if paths else ""))
        except Exception:
            context_lines.append(f"Project context: This is about project id '{project_id}'")

    prompt_parts = [
        "[Intention Delivery]",
        "You have a pending question or comment from idle autonomy.",
        "Generate a single natural chat message to the user that brings this up.",
        "Only ask a question if it is important and specific enough to be worth the interruption. Do not turn filler into a question.",
        "Playful or silly comments are allowed only when the stored content/context shows that tone is welcome.",
        "Be specific and natural, mentioning relevant context so the user knows what you are referring to.",
        "If project context is provided, mention the project name unless the content already makes the project obvious.",
        "Write it as if you are spontaneously speaking to the user. Do not mention autonomy, intentions, or that this was generated.",
        "",
        f"Type: {intention.kind}",
        f"Content: {intention.content}",
    ]
    if context_lines:
        prompt_parts.extend(["", *context_lines])
    prompt_parts.extend([
        "",
        "Return only the message text with no prefix, no explanation, and no JSON formatting.",
    ])

    messages = [
        {"role": "system", "content": "\n".join(prompt_parts)},
        {"role": "user", "content": "Go ahead and say it."},
    ]

    response = collect_model_text(client, messages, model=model)
    if not response:
        return None

    append_chat_message(
        chat_id,
        "assistant",
        response,
        metadata={
            "autonomy_intention_delivery": True,
            "intention_id": intention.id,
            "intention_kind": intention.kind,
        },
    )
    record_intention_surface(chat_id, intention.id, metadata={"kind": intention.kind, "delivery_source": delivery_source})
    mark_intention_used(intention.id)
    record_continuity_event(
        "intention_shown",
        f"Delivered queued {intention.kind}: {intention.content}",
        source="autonomy",
        chat_id=chat_id,
        project_id=str(intention.metadata.get("project_id") or "") if isinstance(intention.metadata, dict) else "",
        metadata={"intention_id": intention.id, "kind": intention.kind},
    )
    return intention


def select_surfaceable_intention(
    *,
    chat_id: str,
    latest_user_text: str,
    response_text: str,
    active_project_id: str = "",
    mode: str = "chat",
    quiet_mode: bool = False,
) -> Intention | None:
    return next_eligible_intention(
        chat_id,
        latest_user_text=latest_user_text,
        active_project_id=active_project_id,
        response_text=response_text,
        mode=mode,
        quiet_mode=quiet_mode,
    )


def surfaced_intention_text(intention: Intention) -> str:
    kind = intention.kind.replace("_", " ")
    if kind == "question":
        label = "a question"
    elif kind in {"comment", "suggestion"}:
        label = f"a {kind}"
    else:
        label = "a thought"
    return f"\n\nAlso, I had {label} saved from earlier: {intention.content}"


def mark_intention_surfaced(chat_id: str, intention: Intention, run_id: str = "") -> None:
    record_intention_surface(chat_id, intention.id, run_id, metadata={"kind": intention.kind})
    mark_intention_shown(intention.id)
