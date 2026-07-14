from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from typing import Any

from .repository import (
    create_assistant_message,
    create_tool_event,
    update_assistant_message,
    update_tool_event,
)
from .state import (
    LAST_PROMPT_USAGE_BY_CHAT_ID,
    LAST_PROMPT_USAGE_LOCK,
    ActiveChatRun,
    ChatCancelled,
    unregister_chat_run,
)
from ..continuity import capture_post_chat_episodic_fallback, record_continuity_event
from ..interactions import parse_question_request, question_answers_tool_result, question_request_to_json
from ..config import load_config
from ..coding.runs import (
    CodingRun,
    complete_coding_run,
    record_coding_run_step,
    should_track_coding_request,
    start_coding_run,
    tool_phase,
)
from ..autonomy.delivery import mark_intention_surfaced, select_surfaceable_intention, surfaced_intention_text
from ..lifecycle import lifecycle_quiet_mode
from ..loop_learning import record_loop_incident
from ..projects.routing import (
    CollectedResponse,
    clean_model_thinking_text,
    clean_user_facing_model_response,
    contains_final_answer_tool_leak,
    may_be_tool_call_prefix,
    may_be_unsupported_tool_prefix,
    response_text_before_unsupported_marker,
)
from ..prompt_builder import latest_user_message, remember_tool_result_context
from ..memory.project import list_projects
from ..memory.steward import project_memory_broker_call
from ..memory.consolidation import cancel_memory_consolidation, schedule_memory_consolidation
from ..providers import ProviderClient
from ..tools import (
    ToolCall,
    ToolExecutor,
    ToolParseError,
    ToolResult,
    contains_tool_call,
    contains_unsupported_tool_output,
    default_tool_registry,
    _strip_system_reminders,
    invalid_tool_result,
    needs_permission,
    normalize_tool_arguments,
    openai_tools_schema,
    parse_tool_call,
    parse_tool_call_lines,
    parse_tool_calls,
    summarize_arguments,
    tool_instruction_message,
)
from ..utils import log_activity
from ..workspace import write_workspace_document


MAX_AUTOMATIC_MEMORY_WRITES = 3
FALLBACK_TOOL_RESULT_CONTENT_CHARS = 12000
ARTIFACT_WRITE_TOOLS = {"write_file", "patch_file", "make_directory"}
ARTIFACT_BACKING_TOOLS = {*ARTIFACT_WRITE_TOOLS, "run_shell_command"}
ARTIFACT_EXTENSIONS_RE = re.compile(r"\.(?:svg|png|jpg|jpeg|gif|webp|pdf|txt|md|mdx|rst|json|jsonc|csv|tsv|yaml|yml|toml|ini|cfg|conf|env|xml|html|css|scss|sass|less|js|jsx|mjs|cjs|ts|tsx|svelte|vue|astro|py|sh|bash|zsh|fish|rune|go|rs|rb|java|kt|c|h|cpp|hpp|cc|cs|php|lua|sql|tex|kicad_pro|kicad_sch|kicad_pcb|sch|pcb)\b", re.IGNORECASE)
ARTIFACT_CREATION_RE = re.compile(r"\b(?:create|created|generate|generated|make|made|save|saved|write|wrote|export|exported|update|updated|edit|edited|modify|modified|tweak|tweaked)\b", re.IGNORECASE)
STUCK_LOOP_MESSAGE = "The model got stuck trying to use tools, so I stopped the tool loop and summarized what I found."


def prompt_has_complete_tool_list(prompt_messages: list[dict[str, str]], registry: Any) -> bool:
    expected_names = [definition.name for definition in registry.definitions()]

    for message in prompt_messages:
        if message.get("role") != "system":
            continue

        content = message.get("content", "")
        if not isinstance(content, str):
            continue

        if "[Available Tools]" not in content and "Available tools:" not in content:
            continue

        if all(name in content for name in expected_names):
            return True

    return False


def ensure_runtime_tool_prompt(prompt_messages: list[dict[str, str]], registry: Any, native_tools: bool = False) -> list[dict[str, str]]:
    """Ensure the exact model call contains the complete tool list.

    This is a runtime safety net, not the main prompt builder. It covers older
    chats, alternate prompt construction paths, and stale first system prompts
    that mention tools without including the actual list.
    """
    if prompt_has_complete_tool_list(prompt_messages, registry):
        return prompt_messages

    return [
        {"role": "system", "content": tool_instruction_message(registry, native_tools=native_tools)["content"]},
        *prompt_messages,
    ]


def stream_tool_calls_to_tool_calls(chunks: list[Any]) -> list[ToolCall]:
    """Convert native StreamToolCall chunks into validated ToolCall objects.

    Argument JSON that fails to parse is skipped so a single malformed native
    call cannot abort the turn; the text-protocol path and salvage net remain
    available as fallbacks.
    """
    calls: list[ToolCall] = []
    for chunk in chunks:
        if getattr(chunk, "kind", "") != "tool_call":
            continue
        stream_call = getattr(chunk, "tool_call", None)
        if stream_call is None or not stream_call.name:
            continue
        raw_arguments = (stream_call.arguments or "").strip()
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(arguments, dict):
            continue
        calls.append(ToolCall(tool=stream_call.name, arguments=normalize_tool_arguments(stream_call.name, arguments)))
    return calls


def post_result_response_is_nonsense(response_text: str, last_successful_tool_result: ToolResult | None) -> bool:
    """Return True when a post-tool response is unusable enough to trigger synthesis repair.

    This intentionally stays conservative. Local models sometimes emit tiny
    fragments, protocol debris, or meta-comments after a useful tool result.
    We should synthesize from the result instead of showing that as the answer.
    """
    if last_successful_tool_result is None:
        return False
    clean = (response_text or "").strip()
    if not clean:
        return True
    lowered = clean.lower()
    if len(clean) < 12 and not any(char.isalnum() for char in clean):
        return True
    if lowered in {"done", "ok", "okay", "tool result", "result", "continue", "final"}:
        return True
    if contains_tool_call(clean) or contains_unsupported_tool_output(clean):
        return True
    return False


def recovery_message_from_tool_result(result: ToolResult | None) -> str:
    if result is None:
        return STUCK_LOOP_MESSAGE + " I do not have a usable tool result yet, so please try again or give me a little more direction."
    summary = result.summary.strip() or f"{result.tool} completed"
    content = result.content.strip()
    if content:
        clipped = content[:FALLBACK_TOOL_RESULT_CONTENT_CHARS].rstrip()
        return f"{STUCK_LOOP_MESSAGE}\n\n{summary}\n\n{clipped}"
    return f"{STUCK_LOOP_MESSAGE}\n\n{summary}"


def return_greeting_context_message(greeting_text: str) -> dict[str, str] | None:
    greeting = greeting_text.strip()
    if not greeting:
        return None

    return {
        "role": "system",
        "content": "\n".join(
            [
                "[Return Greeting Context]",
                "The user has returned after a long idle gap.",
                f"Configured acknowledgment: {greeting}",
                "Use this only as private context for the next reply.",
                "If you acknowledge the return, do it once naturally and do not stack it with a separate time-of-day greeting.",
                "Do not mention this context block.",
            ]
        ),
    }


def conversation_timing_context_message(gap_minutes: int | None, gap_label: str) -> dict[str, str] | None:
    if gap_minutes is None or gap_minutes < 0 or not gap_label:
        return None
    return {
        "role": "system",
        "content": "\n".join(
            [
                "[Conversation Timing Context]",
                f"It has been {gap_label} since the user's last chat message ({gap_minutes} minutes).",
                "Keep this as quiet background context, not a required greeting or topic.",
                "Do not mention the gap for ordinary or short absences. For a substantial gap, you may warmly and lightly acknowledge the return when it genuinely fits the reply.",
                "A little tenderness is welcome, but never guilt the user, imply you were waiting, or state the exact duration unless it is relevant or they ask.",
                "Do not mention this context block.",
            ]
        ),
    }


def project_display_name(project_id: str) -> str:
    if not project_id:
        return ""

    try:
        project = next((project for project in list_projects() if project.id == project_id), None)
    except Exception:
        return project_id

    return project.name if project is not None else project_id


def tool_call_announcement(call: ToolCall) -> str:
    # Tool event cards already show progress. Avoid adding a separate assistant
    # message like "I'll run the tool..." before every tool call.
    return ""


def tool_call_thinking(call: ToolCall) -> str:
    if call.tool in {"record_episode", "update_episode", "forget_episode", "record_project_memory", "update_project_memory", "record_memory", "write_memory", "update_memory", "archive_memory", "move_memory", "merge_memory"}:
        return ""

    if call.tool == "get_project_brief":
        project_id = str(call.arguments.get("project_id", "")).strip()
        project_name = project_display_name(project_id)
        target = f" {project_name}" if project_name else ""
        return f"Found the project{target}; pulling up the briefing now."

    if call.tool == "get_project_memory":
        project_id = str(call.arguments.get("project_id", "")).strip()
        target = f" for `{project_id}`" if project_id else ""
        return f"Loading deeper project memory{target}."

    if call.tool == "read_file":
        file_path = str(call.arguments.get("file_path", "")).strip()
        if file_path:
            return f"Reading `{file_path}` so the answer can use exact project context."
        return "Reading the requested project file."

    if call.tool == "run_shell_command":
        return "Executing the requested terminal command."

    if call.tool.startswith("mcp_"):
        return "Using an MCP-backed capability."

    if call.tool == "load_skill":
        name = str(call.arguments.get("name", "")).strip()
        return f"Loading the `{name}` skill." if name else "Loading the selected skill."

    if call.tool in {"list_skills", "validate_skill"}:
        return "Checking BitBuddy's skill library."

    return "Running the selected tool."


def tool_signature(call: ToolCall) -> str:
    return f"{call.tool}:{json.dumps(call.arguments, sort_keys=True)}"


def tool_effect_key(call: ToolCall) -> str | None:
    """Return a semantic key for mutating tool side effects.

    Exact JSON matching is not enough for model-driven tools: the model can
    repeat the same action with a slightly different description or argument
    order. Effect keys intentionally ignore non-identifying fields for tools
    where repeated execution would duplicate external/local state.
    """
    tool = call.tool
    arguments = call.arguments
    if tool == "calendar_create_event":
        return "calendar_create:" + "|".join(
            [
                _normalize_effect_text(arguments.get("title")),
                _normalize_effect_datetime(arguments.get("start")),
                _normalize_effect_datetime(arguments.get("end")),
                _normalize_effect_text(arguments.get("location")),
            ]
        )
    if tool in {"calendar_modify_event", "calendar_delete_event"}:
        event_id = _normalize_effect_text(arguments.get("event_id"))
        return f"{tool}:{event_id}" if event_id else tool_signature(call)
    if tool in {"write_file", "patch_file", "make_directory"}:
        target = arguments.get("file_path") or arguments.get("path") or ""
        identity = {
            "project_id": _normalize_effect_text(arguments.get("project_id")),
            "root_path": _normalize_effect_text(arguments.get("root_path")),
            "target": _normalize_effect_text(target),
        }
        if tool == "write_file":
            identity["content"] = str(arguments.get("content") or "")
            identity["overwrite"] = bool(arguments.get("overwrite", False))
        elif tool == "patch_file":
            identity["old_text"] = str(arguments.get("old_text") or "")
            identity["new_text"] = str(arguments.get("new_text") or "")
            identity["replace_all"] = bool(arguments.get("replace_all", False))
        else:
            identity["parents"] = bool(arguments.get("parents", True))
            identity["exist_ok"] = bool(arguments.get("exist_ok", True))
        return f"{tool}:{json.dumps(identity, sort_keys=True)}"
    if tool == "run_shell_command":
        return "run_shell_command:" + json.dumps(
            {
                "command": " ".join(str(arguments.get("command") or "").split()),
                "working_directory": _normalize_effect_text(arguments.get("working_directory")),
            },
            sort_keys=True,
        )
    if tool in {"record_episode", "update_episode", "forget_episode", "record_project_memory", "update_project_memory", "record_memory", "write_memory", "update_memory", "archive_memory", "move_memory", "merge_memory", "create_skill", "patch_skill", "archive_skill", "write_skill_file"}:
        cleaned = {key: value for key, value in arguments.items() if key != "conversation_id"}
        return f"{tool}:{json.dumps(cleaned, sort_keys=True, default=str)}"
    return None


def _normalize_effect_text(value: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value or "").casefold()).split())


def _normalize_effect_datetime(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        from ..calendar.service import user_timezone
        from ..calendar.store import to_utc_iso

        return to_utc_iso(raw, fallback_tz=user_timezone())
    except Exception:
        return _normalize_effect_text(raw)



def final_tool_fallback_message(result: ToolResult | None) -> str:
    """Last-resort error text after synthesis repair fails.

    This deliberately does not summarize tool output with regexes or templates.
    The model gets repair attempts first; this message is only an honest error
    boundary if the provider still cannot produce a clean user-facing answer.
    """
    if result is None:
        return "I couldn't complete that because no successful tool result was available."

    summary = result.summary.strip()
    if summary:
        return (
            f"{summary}\n\n"
            "I got the tool result, but I still could not get a clean user-facing synthesis from the model after retrying."
        )

    return "The tool completed, but I still could not get a clean user-facing synthesis from the model after retrying."


def is_tool_instruction_or_protocol_message(message: dict[str, str]) -> bool:
    if message.get("role") != "system":
        return False

    content = message.get("content", "")
    if not isinstance(content, str):
        return False

    markers = (
        "[Available Tools]",
        "Tool call format:",
        "tool_call: {",
        "Your previous response looked like a tool call",
        "Your previous response used malformed or unsupported tool syntax",
        "This tool call was already executed",
        "That tool call was already queued or executed",
        "The tool-call round limit was reached",
    )
    return any(marker in content for marker in markers)


def tool_synthesis_messages(
    messages: list[dict[str, str]],
    *,
    reason: str,
    attempt: int,
) -> list[dict[str, str]]:
    """Build a tool-disabled repair prompt that still lets the model reason.

    The tool result remains in the prompt as private working context.  Tool
    instructions/protocol repair messages are removed so the provider is not
    nudged back into another tool call when the next required behavior is plain
    synthesis.
    """
    clean_messages = [message for message in messages if not is_tool_instruction_or_protocol_message(message)]
    clean_messages.append(
        {
            "role": "system",
            "content": "\n".join(
                [
                    "[Tool Result Synthesis Repair]",
                    "A previous model response after a successful tool result was not safe to show directly.",
                    f"Reason: {reason}",
                    f"Repair attempt: {attempt}",
                    "Tools are disabled for this repair pass. Do not output a tool call.",
                    "Use the successful tool result already present in the conversation as private working context.",
                    "Use your normal reasoning/thinking if the provider supports it, but keep that reasoning out of the final answer.",
                    "Answer the user's latest request directly and substantively from the tool result.",
                    "Do not mention parser failures, runtime details, fallback behavior, or tool mechanics.",
                    "Do not paste raw file/tool output unless the user explicitly asked for raw/full output.",
                ]
            ),
        }
    )
    return clean_messages


def clean_synthesis_text(text: str) -> str:
    return clean_user_facing_model_response(_strip_system_reminders(text))


def synthesis_text_is_clean(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return False
    if contains_tool_call(clean):
        return False
    if contains_unsupported_tool_output(clean):
        return False
    if contains_final_answer_tool_leak(clean):
        return False
    return True


def artifact_request_or_claim(user_text: str, response_text: str) -> bool:
    combined = "\n".join([user_text or "", response_text or ""])
    if not ARTIFACT_CREATION_RE.search(combined):
        return False
    if ARTIFACT_EXTENSIONS_RE.search(combined):
        return True
    lowered = combined.lower()
    return any(word in lowered for word in (" svg", "file", "artifact", "script", "logo", "image"))


def response_claims_file_created(response_text: str) -> bool:
    text = response_text or ""
    if re.search(r"\b(?:saved|created|wrote|generated|exported|updated|edited|modified|tweaked)\s+(?:to|at|as)?\b", text, flags=re.IGNORECASE) and ARTIFACT_EXTENSIONS_RE.search(text):
        return True
    if re.search(r"\b(?:saved|created|wrote|generated|exported|updated|edited|modified|tweaked)\b", text, flags=re.IGNORECASE) and ARTIFACT_EXTENSIONS_RE.search(text):
        return True
    return False


def has_backing_artifact_tool_result(results: list[ToolResult]) -> bool:
    return any(result.ok and result.tool in ARTIFACT_BACKING_TOOLS for result in results)


def should_repair_unbacked_artifact_response(user_text: str, response_text: str, results: list[ToolResult]) -> bool:
    if has_backing_artifact_tool_result(results):
        return False
    if response_claims_file_created(response_text):
        return True
    return artifact_request_or_claim(user_text, "")


def artifact_creation_repair_message(user_text: str, response_text: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": "\n".join(
            [
                "Your previous response was not shown to the user because it implied a file/artifact was created without running any file-writing or generation tool.",
                "If the user asks to create, save, write, generate, export, update, edit, modify, or tweak a file, you must actually mutate it with tools.",
                "For simple content, call write_file with a relative file_path under ~/.bitbuddy/artifacts.",
                "For existing files you have just read, call patch_file or write_file to update that same file before saying it was updated.",
                "For procedural content, call write_file to create a generator script, then run_shell_command with working_directory to execute it, then verify with list_directory or read_file.",
                "Output only valid tool_call JSON lines now; do not answer in prose until the file has been created and verified.",
                f"User request: {user_text[:500]}",
                f"Blocked response excerpt: {response_text[:500]}",
            ]
        ),
    }


WORKING_PLAN_MARKER = "__working_plan_note__"
WORKING_PLAN_MAX_CHARS = 700


def compact_plan_from_thinking(thinking_text: str) -> str:
    """Extract a compact plan from a round's reasoning to carry into later rounds.

    Keeps the tail of the reasoning (where the concrete plan/decision usually
    lands) capped to a small budget, so the model continues the task it already
    reasoned through instead of re-deriving it from scratch each tool round.
    """
    lines = [line.strip() for line in (thinking_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        if total + len(line) + 1 > WORKING_PLAN_MAX_CHARS and kept:
            break
        kept.append(line)
        total += len(line) + 1
    kept.reverse()
    return "\n".join(kept).strip()


def working_plan_note(thinking_text: str) -> dict[str, str] | None:
    """Build a private continuity note carrying the model's own working plan.

    Returns None when there is no substantive plan to carry. Uses role='user'
    working-context (like tool results) because local chat templates include it
    far more reliably than a late system message.
    """
    plan = compact_plan_from_thinking(thinking_text)
    if not plan:
        return None
    return {
        "role": "user",
        "content": "\n".join(
            [
                "[Your Working Plan — private continuity context, not a new user request]",
                "This is the plan you already worked out earlier in THIS task. Do not re-derive it "
                "from scratch. Continue executing it: call the next tool the plan needs rather than "
                "describing the change in prose.",
                "",
                plan,
            ]
        ),
        WORKING_PLAN_MARKER: True,
    }


FENCED_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
MIN_SALVAGE_CHARS = 80


def salvage_authored_content(response_text: str) -> tuple[str, str] | None:
    """Recover substantive authored content from a reply that claimed a file but
    never ran a write tool, so the work is saved instead of discarded.

    Prefers the largest fenced code block; otherwise falls back to the whole
    reply. Returns (title, body) or None when there is nothing worth keeping.
    """
    text = (response_text or "").strip()
    if not text:
        return None
    blocks = [match.group(1).strip() for match in FENCED_BLOCK_RE.finditer(text)]
    blocks = [block for block in blocks if block]
    body = max(blocks, key=len) if blocks else text
    if len(body) < MIN_SALVAGE_CHARS:
        return None
    title = "Salvaged draft"
    for line in body.splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            title = candidate[:80]
            break
    return title, body


def start_chat_run(run: ActiveChatRun) -> None:
    cancel_memory_consolidation(run.chat_id, reason="new chat run started")

    def generate() -> None:
        config = load_config()
        client = ProviderClient(config.provider)
        max_tool_rounds = config.chat.max_tool_rounds
        registry = default_tool_registry()
        mode_context = latest_user_message(run.prompt_messages)
        executor = ToolExecutor(registry, mode=run.mode, mode_context=mode_context)

        # Native function calling is the primary tool transport when the provider
        # supports it (cached probe). Falls back to the text tool protocol otherwise.
        native_tools = client.supports_native_tools(run.model)
        tools_schema = openai_tools_schema(registry, run.mode) if native_tools else None

        last_persist_at = 0.0
        assistant_create_retry_at = 0.0
        persist_retry_at = 0.0
        last_persist_error = ""
        fallback_tool_event_id = -1
        suppress_system_reminder_thinking = False
        suppress_system_reminder_response = False

        def persist(force: bool = False) -> None:
            nonlocal last_persist_at, persist_retry_at, last_persist_error

            now = time.monotonic()

            if not force and now - last_persist_at < 0.25:
                return

            if not force and now < persist_retry_at:
                return

            if run.assistant_message_id is None:
                return

            try:
                update_assistant_message(run.assistant_message_id, run.assistant_text, run.thinking_text)
                last_persist_at = now
                last_persist_error = ""
            except (sqlite3.Error, OSError) as error:
                message = str(error)

                if message != last_persist_error:
                    print(f"BitBuddy chat persistence failed: {message}", file=sys.stderr)
                    last_persist_error = message

                persist_retry_at = now + 2.0
                last_persist_at = now

        def record_prompt_usage(label: str, prompt_messages: list[dict[str, str]]) -> None:
            """Record the exact prompt size for a real model call."""
            try:
                token_count = client.count_tokens(prompt_messages, model=run.model)
                context_window = client.context_window(model=run.model)

                usage = {
                    "chat_id": run.chat_id,
                    "label": label,
                    "provider": context_window.get("provider"),
                    "model": context_window.get("model"),
                    "used_tokens": token_count.get("used_tokens"),
                    "context_window_tokens": context_window.get("context_window_tokens"),
                    "usage_source": token_count.get("source"),
                    "window_source": context_window.get("source"),
                    "message_count": len(prompt_messages),
                    "measurement": "runtime_actual",
                    "created_at": time.time(),
                }
            except Exception as error:
                usage = {
                    "chat_id": run.chat_id,
                    "label": label,
                    "used_tokens": None,
                    "context_window_tokens": None,
                    "usage_source": "error",
                    "window_source": "error",
                    "message_count": len(prompt_messages),
                    "measurement": "runtime_actual",
                    "error": str(error),
                    "created_at": time.time(),
                }

            with run.lock:
                run.context_usage = usage

            with LAST_PROMPT_USAGE_LOCK:
                LAST_PROMPT_USAGE_BY_CHAT_ID[run.chat_id] = usage

            run.broadcast({"kind": "context_usage", "usage": usage, **usage})

            log_activity(
                "chat.prompt_usage",
                f"{label}: {usage.get('used_tokens')} token(s)",
                usage,
            )

        def throw_if_cancelled() -> None:
            if run.cancel_requested.is_set():
                raise ChatCancelled()

        def ensure_assistant_message() -> None:
            nonlocal assistant_create_retry_at

            if run.assistant_message_id is not None:
                return

            now = time.monotonic()

            if now < assistant_create_retry_at:
                return

            try:
                run.assistant_message_id = create_assistant_message(run.chat_id, mode=run.mode)
            except (sqlite3.Error, OSError) as error:
                print(f"BitBuddy assistant-message persistence failed: {error}", file=sys.stderr)
                assistant_create_retry_at = now + 2.0

        def emit_chunk(chunk: Any) -> None:
            throw_if_cancelled()
            ensure_assistant_message()

            if chunk.kind == "response":
                run.assistant_text += chunk.text
            elif chunk.kind == "thinking":
                if not run.thinking_enabled:
                    return
                run.thinking_text += chunk.text

            persist()
            run.broadcast({"kind": chunk.kind, "text": chunk.text})

        def emit_collected_response(collection: CollectedResponse) -> None:
            if not collection.thinking_emitted:
                thinking_text = "".join(
                    chunk.text
                    for chunk in collection.chunks
                    if chunk.kind == "thinking" and chunk.text
                )
                emit_thinking_text(clean_model_thinking_text(thinking_text))

            if not collection.response_emitted:
                clean_response = clean_synthesis_text(collection.response_text)
                if clean_response:
                    emit_text(clean_response)
                return

            for chunk in collection.chunks:
                if chunk.kind == "thinking":
                    continue

                if chunk.kind == "response" and collection.response_emitted:
                    continue

                emit_chunk(chunk)

        def emit_text(text: str) -> None:
            throw_if_cancelled()
            ensure_assistant_message()

            leading_separator = leading_text_separator(text)
            text = strip_live_system_reminder_response(text)
            if leading_separator and text and run.assistant_text and not run.assistant_text[-1].isspace():
                text = leading_separator + text.lstrip()
            if not text:
                return

            run.assistant_text += text

            persist(force=True)
            run.broadcast({"kind": "response", "text": text})

        def leading_text_separator(text: str) -> str:
            if text.startswith("\n\n"):
                return "\n\n"
            if text[:1].isspace():
                return " "
            return ""

        def strip_live_system_reminder_response(text: str) -> str:
            nonlocal suppress_system_reminder_response

            remaining = text
            out = ""
            close_tag = "</system-reminder>"

            while remaining:
                lowered = remaining.lower()
                if suppress_system_reminder_response:
                    end = lowered.find(close_tag)
                    if end == -1:
                        return out
                    remaining = remaining[end + len(close_tag):]
                    suppress_system_reminder_response = False
                    continue

                start = lowered.find("<system-reminder")
                if start == -1:
                    out += remaining
                    break

                out += remaining[:start]
                end = lowered.find(close_tag, start)
                if end == -1:
                    suppress_system_reminder_response = True
                    break
                remaining = remaining[end + len(close_tag):]

            return _strip_system_reminders(out)

        def emit_thinking_text(text: str) -> None:
            """Emit already-sanitized model thinking text."""
            if not run.thinking_enabled:
                return

            clean = text.strip()

            if not clean:
                return

            throw_if_cancelled()
            ensure_assistant_message()

            if run.thinking_text and not run.thinking_text.endswith("\n"):
                run.thinking_text += "\n"

            run.thinking_text += clean + "\n"

            persist(force=True)
            run.broadcast({"kind": "thinking", "text": clean + "\n"})

        def finish_current_assistant_turn() -> None:
            nonlocal last_persist_at

            if run.assistant_message_id is None:
                return

            persist(force=True)

            run.assistant_message_id = None
            run.assistant_text = ""
            run.thinking_text = ""
            last_persist_at = 0.0

        def emit_live_clean_thinking_line(raw_line: str, phase: str) -> int:
            raw_line = strip_live_system_reminder_thinking(raw_line)
            if not raw_line.strip():
                return 0

            cleaned = clean_model_thinking_text(raw_line, phase=phase)

            if not cleaned:
                return 0

            emit_thinking_text(cleaned)

            return len(cleaned) + 1

        def strip_live_system_reminder_thinking(text: str) -> str:
            nonlocal suppress_system_reminder_thinking

            remaining = text
            out = ""
            close_tag = "</system-reminder>"

            while remaining:
                lowered = remaining.lower()
                if suppress_system_reminder_thinking:
                    end = lowered.find(close_tag)
                    if end == -1:
                        return out
                    remaining = remaining[end + len(close_tag):]
                    suppress_system_reminder_thinking = False
                    continue

                start = lowered.find("<system-reminder")
                if start == -1:
                    out += remaining
                    break

                out += remaining[:start]
                end = lowered.find(close_tag, start)
                if end == -1:
                    suppress_system_reminder_thinking = True
                    break
                remaining = remaining[end + len(close_tag):]

            return out

        def collect_response(
            prompt_messages: list[dict[str, str]],
            live: bool = False,
            live_thinking: bool = False,
            thinking_phase: str = "final",
            prompt_label: str = "",
            allow_tools: bool = True,
        ) -> CollectedResponse:
            throw_if_cancelled()
            if allow_tools:
                prompt_messages = ensure_runtime_tool_prompt(prompt_messages, registry, native_tools=native_tools)
            else:
                prompt_messages = [
                    message
                    for message in prompt_messages
                    if not is_tool_instruction_or_protocol_message(message)
                ]
            record_prompt_usage(prompt_label or f"{thinking_phase}_prompt", prompt_messages)

            chunks: list[Any] = []
            response_parts: list[str] = []
            guarded_response = ""
            response_released = False
            response_emitted = False
            response_blocked = False
            thinking_emitted = False
            thinking_buffer = ""
            stream_tools = tools_schema if (allow_tools and native_tools) else None
            for chunk in client.stream_chat(prompt_messages, model=run.model, should_cancel=run.cancel_requested.is_set, thinking_enabled=run.thinking_enabled, tools=stream_tools):
                throw_if_cancelled()
                chunks.append(chunk)

                if chunk.kind == "thinking":
                    if live_thinking and chunk.text:
                        thinking_buffer += chunk.text

                        while "\n" in thinking_buffer:
                            line, thinking_buffer = thinking_buffer.split("\n", 1)
                            emit_live_clean_thinking_line(line, thinking_phase)
                            thinking_emitted = True
                    elif live:
                        emit_chunk(chunk)
                        thinking_emitted = True

                    continue

                if chunk.kind != "response":
                    continue

                response_parts.append(chunk.text)

                if not live:
                    continue

                if response_released:
                    safe_text = response_text_before_unsupported_marker(chunk.text)

                    if safe_text:
                        emit_text(safe_text)
                        response_emitted = True

                    if safe_text != chunk.text:
                        response_blocked = True

                    if response_blocked:
                        continue

                    continue

                guarded_response += chunk.text

                if may_be_tool_call_prefix(guarded_response) or may_be_unsupported_tool_prefix(guarded_response):
                    continue

                response_released = True
                safe_text = response_text_before_unsupported_marker(guarded_response)

                if safe_text:
                    emit_text(safe_text)
                    response_emitted = True

                if safe_text != guarded_response:
                    response_blocked = True

                guarded_response = ""

            throw_if_cancelled()

            if live_thinking and thinking_buffer.strip():
                emit_live_clean_thinking_line(thinking_buffer, thinking_phase)
                thinking_emitted = True

            response_text = "".join(response_parts)

            if (
                live
                and guarded_response
                and not response_blocked
                and not contains_tool_call(response_text)
                and not contains_unsupported_tool_output(response_text)
            ):
                emit_text(guarded_response)
                response_emitted = True

            native_tool_calls = stream_tool_calls_to_tool_calls(chunks) if native_tools else []
            return CollectedResponse(chunks, response_text, response_emitted, thinking_emitted, tool_calls=native_tool_calls)

        def broadcast_tool_event(sse_kind: str, event: dict[str, object]) -> None:
            metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}

            sse_event = {
                "kind": sse_kind,
                "event": event,
                "id": event.get("id"),
                "tool": metadata.get("tool") if isinstance(metadata, dict) else "",
                "status": event.get("status", ""),
                "arguments_summary": metadata.get("arguments_summary", {}) if isinstance(metadata, dict) else {},
                "result_summary": metadata.get("result_summary", "") if isinstance(metadata, dict) else "",
                "error": metadata.get("error", "") if isinstance(metadata, dict) else "",
            }

            with run.lock:
                run.tool_events = [existing for existing in run.tool_events if existing.get("id") != sse_event.get("id")]
                run.tool_events.append(sse_event)

            run.broadcast(sse_event)

        def fallback_tool_event(
            tool: str,
            arguments_summary: dict[str, object],
            summary: str,
            status: str = "running",
            error: str = "",
            mode: str = "",
            metadata_patch: dict[str, object] | None = None,
        ) -> dict[str, object]:
            nonlocal fallback_tool_event_id

            fallback_tool_event_id -= 1

            metadata = {
                "tool": tool,
                "arguments_summary": arguments_summary,
                "result_summary": summary if status == "completed" else "",
                "error": error,
                "truncated": False,
                "raw_result_visible": False,
                "persistence_failed": True,
            }
            if metadata_patch:
                metadata.update(metadata_patch)
                metadata["persistence_failed"] = True

            return {
                "id": fallback_tool_event_id,
                "role": "tool",
                "content": summary.strip()[:500],
                "thinking_content": "",
                "created_at": "",
                "kind": "tool",
                "status": status,
                "sequence": 0,
                "parent_message_id": None,
                "mode": mode,
                "metadata": metadata,
            }

        def create_runtime_tool_event(
            chat_id: str,
            tool: str,
            arguments_summary: dict[str, object],
            summary: str,
            sequence: int | None = None,
            parent_message_id: int | None = None,
            mode: str = "",
        ) -> dict[str, object]:
            try:
                return create_tool_event(chat_id, tool, arguments_summary, summary, sequence=sequence, parent_message_id=parent_message_id, mode=mode)
            except (sqlite3.Error, OSError) as error:
                print(f"BitBuddy tool-event persistence failed: {error}", file=sys.stderr)

                return fallback_tool_event(
                    tool,
                    arguments_summary,
                    summary,
                    status="running",
                    error=str(error),
                    mode=mode,
                )

        def update_runtime_tool_event(
            event_id: int,
            status: str,
            summary: str,
            metadata_patch: dict[str, object] | None = None,
        ) -> dict[str, object]:
            metadata = metadata_patch or {}
            tool = str(metadata.get("tool") or "tool")
            arguments_summary = metadata.get("arguments_summary") if isinstance(metadata.get("arguments_summary"), dict) else {}
            error_text = str(metadata.get("error") or "")

            if event_id > 0:
                try:
                    return update_tool_event(event_id, status, summary, metadata_patch)
                except (sqlite3.Error, OSError) as error:
                    print(f"BitBuddy tool-result persistence failed: {error}", file=sys.stderr)

                    if not error_text:
                        error_text = str(error)

            return fallback_tool_event(
                tool,
                arguments_summary,
                summary,
                status=status,
                error=error_text,
                metadata_patch=metadata,
            )

        try:
            messages = run.prompt_messages
            timing_message = conversation_timing_context_message(run.conversation_gap_minutes, run.conversation_gap_label)
            if timing_message is not None:
                messages = [*messages, timing_message]
            return_greeting_message = return_greeting_context_message(run.return_greeting_text)
            if return_greeting_message is not None:
                messages = [*messages, return_greeting_message]
                log_activity(
                    "chat.return_greeting",
                    "Injected return greeting context after long idle gap",
                    {"chat_id": run.chat_id, "run_id": run.run_id},
                )
            initial_latest_user_text = latest_user_message(run.prompt_messages)
            tool_rounds = 0
            unsupported_tool_rounds = 0
            malformed_tool_rounds = 0
            duplicate_tool_rounds = 0
            artifact_creation_repair_rounds = 0
            called_tools_signatures: set[str] = set()
            called_tool_effect_keys: set[str] = set()
            pending_tool_calls: list[ToolCall] = []
            last_successful_tool_result: ToolResult | None = None
            all_successful_tool_results: list[ToolResult] = []
            successful_tool_results: list[ToolResult] = []
            coding_run: CodingRun | None = None
            coding_run_saw_inspect = False
            coding_run_saw_plan = False

            def enqueue_tool_calls(calls: list[ToolCall]) -> int:
                queued_signatures = {tool_signature(call) for call in pending_tool_calls}
                queued_effect_keys = {key for call in pending_tool_calls if (key := tool_effect_key(call)) is not None}
                added = 0

                for call in calls:
                    signature = tool_signature(call)
                    effect_key = tool_effect_key(call)

                    if signature in called_tools_signatures or signature in queued_signatures:
                        continue
                    if effect_key is not None and (effect_key in called_tool_effect_keys or effect_key in queued_effect_keys):
                        continue

                    pending_tool_calls.append(call)
                    queued_signatures.add(signature)
                    if effect_key is not None:
                        queued_effect_keys.add(effect_key)
                    added += 1

                return added

            def ensure_coding_run(project_id: str = "") -> CodingRun | None:
                nonlocal coding_run
                if coding_run is not None:
                    return coding_run
                if not should_track_coding_request(initial_latest_user_text):
                    return None
                coding_run = start_coding_run(
                    chat_id=run.chat_id,
                    run_id=run.run_id,
                    project_id=project_id,
                    user_request=initial_latest_user_text,
                    metadata={"mode": run.mode, "model": run.model or config.provider.model},
                )
                log_activity(
                    "coding_run.started",
                    "Started coding work loop",
                    {"coding_run_id": coding_run.id, "chat_id": run.chat_id, "project_id": project_id},
                )
                return coding_run

            def record_coding_tool_result(tool_call: ToolCall, result: ToolResult) -> None:
                nonlocal coding_run, coding_run_saw_inspect, coding_run_saw_plan
                phase = tool_phase(tool_call.tool, tool_call.arguments)
                if phase == "requested":
                    return
                project_id = ""
                if isinstance(result.arguments_summary, dict):
                    raw_project = result.arguments_summary.get("project_id")
                    project_id = str(raw_project or "").strip()
                if not project_id:
                    raw_project = tool_call.arguments.get("project_id")
                    project_id = str(raw_project or "").strip() if isinstance(raw_project, str) else ""
                active = ensure_coding_run(project_id)
                if active is None:
                    return
                if phase == "inspect":
                    coding_run_saw_inspect = True
                if phase == "edit" and coding_run_saw_inspect and not coding_run_saw_plan:
                    coding_run = record_coding_run_step(
                        active.id,
                        phase="plan",
                        kind="runtime",
                        status="completed",
                        summary="Moved from inspection into an edit step.",
                        project_id=project_id,
                        metadata={"trigger_tool": tool_call.tool},
                    )
                    coding_run_saw_plan = True
                coding_run = record_coding_run_step(
                    active.id,
                    phase=phase,
                    kind="tool",
                    tool=result.tool,
                    status="completed" if result.ok else "error",
                    summary=result.summary,
                    project_id=project_id,
                    metadata={
                        "arguments_summary": result.arguments_summary,
                        "error": result.error if not result.ok else "",
                    },
                )

            def tool_protocol_error_event(summary: str, error: str) -> None:
                tool_event = create_runtime_tool_event(
                    run.chat_id,
                    "unsupported_tool_syntax",
                    {},
                    summary,
                    mode=run.mode,
                )
                broadcast_tool_event("tool_call", tool_event)

                try:
                    event_id = int(tool_event.get("id", 0))
                except (TypeError, ValueError):
                    event_id = 0

                updated_event = update_runtime_tool_event(
                    event_id,
                    "error",
                    error,
                    {
                        "tool": "unsupported_tool_syntax",
                        "arguments_summary": {},
                        "result_summary": "",
                        "error": error,
                        "truncated": False,
                        "raw_result_visible": False,
                    },
                )
                broadcast_tool_event("tool_error", updated_event)
                log_activity(
                    "tool.failed",
                    "Blocked unsupported tool syntax",
                    {"tool": "unsupported_tool_syntax", "error": error},
                )

            def response_uses_unsupported_tool_syntax(text: str) -> bool:
                """Check for unsupported tool syntax markers in model output."""
                return contains_unsupported_tool_output(text)

            def fallback_answer_from_last_successful_tool() -> str:
                """Return a last-resort error after model synthesis repair fails."""
                return final_tool_fallback_message(last_successful_tool_result)

            def recover_stuck_loop(reason: str, *, tools: list[str] | None = None, detail: str = "") -> None:
                """Stop a non-progressing tool loop with a useful user-facing recovery."""
                clean_tools = tools or ([last_successful_tool_result.tool] if last_successful_tool_result is not None else [])
                record_loop_incident(
                    provider=config.provider.type,
                    model=run.model or config.provider.model,
                    mode=run.mode,
                    reason=reason,
                    tools=clean_tools,
                    recovery="synthesize_from_last_successful_tool" if last_successful_tool_result is not None else "friendly_stop",
                    chat_id=run.chat_id,
                    run_id=run.run_id,
                    metadata={
                        "detail": detail[:500],
                        "tool_rounds": tool_rounds,
                        "malformed_tool_rounds": malformed_tool_rounds,
                        "unsupported_tool_rounds": unsupported_tool_rounds,
                        "duplicate_tool_rounds": duplicate_tool_rounds,
                    },
                )
                if last_successful_tool_result is not None:
                    if not emit_synthesis_from_last_successful_tool(reason):
                        emit_text(recovery_message_from_tool_result(last_successful_tool_result))
                    return
                emit_text(recovery_message_from_tool_result(None))

            def emit_synthesis_from_last_successful_tool(reason: str) -> bool:
                """Ask the model to synthesize from the last successful tool result.

                This is the main recovery path after a successful read_file or
                project-memory tool.  It is intentionally model-based rather than
                heuristic-based: the runtime disables tools, preserves the tool
                result as private context, lets the provider use thinking, and
                only accepts a clean normal answer.
                """
                if last_successful_tool_result is None:
                    return False

                for attempt in range(1, 3):
                    throw_if_cancelled()
                    repair_messages = tool_synthesis_messages(messages, reason=reason, attempt=attempt)
                    collection = collect_response(
                        repair_messages,
                        live=False,
                        live_thinking=True,
                        thinking_phase="tool_synthesis",
                        prompt_label=f"tool_synthesis_repair_{attempt}",
                        allow_tools=False,
                    )
                    clean_text = clean_synthesis_text(collection.response_text)

                    if synthesis_text_is_clean(clean_text):
                        emit_text(clean_text)
                        log_activity(
                            "tool.synthesis_repaired",
                            "Model produced clean synthesis from successful tool result",
                            {
                                "tool": last_successful_tool_result.tool,
                                "reason": reason,
                                "attempt": attempt,
                            },
                        )
                        return True

                    log_activity(
                        "tool.synthesis_retry_failed",
                        "Model synthesis repair did not produce a clean answer",
                        {
                            "tool": last_successful_tool_result.tool,
                            "reason": reason,
                            "attempt": attempt,
                            "response": collection.response_text[:500],
                        },
                    )

                return False

            def missing_required_arguments(call: ToolCall) -> list[str]:
                """Return required schema keys that are absent or blank before a tool is announced/executed."""
                definition = registry.definition(call.tool)
                if definition is None:
                    return []

                schema = definition.arguments_schema
                required = schema.get("required", []) if isinstance(schema, dict) else []
                if not isinstance(required, list):
                    return []

                missing: list[str] = []
                for key in required:
                    if not isinstance(key, str):
                        continue

                    value = call.arguments.get(key)
                    if value is None:
                        missing.append(key)
                    elif isinstance(value, str) and not value.strip():
                        missing.append(key)

                return missing

            def suppress_incomplete_tool_after_success(call: ToolCall, missing: list[str]) -> bool:
                """Hide incomplete post-result tool calls and push the model to answer from the result."""
                nonlocal malformed_tool_rounds

                if last_successful_tool_result is None or not missing:
                    return False

                malformed_tool_rounds += 1
                log_activity(
                    "tool.incomplete_after_result",
                    "Suppressed incomplete tool call after successful tool result",
                    {
                        "tool": call.tool,
                        "missing_arguments": missing,
                        "arguments": summarize_arguments(call.arguments),
                    },
                )

                if not emit_synthesis_from_last_successful_tool("incomplete tool call after successful tool result"):
                    emit_text(fallback_answer_from_last_successful_tool())
                return True

            def handle_parsed_tool_calls(tool_calls: list[ToolCall], *, recovered_from_prose: bool = False) -> str:
                """Validate and enqueue parsed tool calls.

                Returns "continue" when the model loop should continue and
                "stop" when this turn has been completed by a fallback/synthesis path.
                """
                nonlocal duplicate_tool_rounds, malformed_tool_rounds

                for tool_call in tool_calls:
                    missing_arguments = missing_required_arguments(tool_call)
                    if missing_arguments and suppress_incomplete_tool_after_success(tool_call, missing_arguments):
                        return "stop"
                    if missing_arguments:
                        raise ToolParseError(
                            "Tool call is missing required argument(s): " + ", ".join(missing_arguments)
                        )

                added_tool_calls = enqueue_tool_calls(tool_calls)

                if added_tool_calls:
                    malformed_tool_rounds = 0
                    duplicate_tool_rounds = 0
                    if recovered_from_prose:
                        log_activity(
                            "tool.recovered",
                            "Recovered tool calls from prose-wrapped model output",
                            {"tools": [call.tool for call in tool_calls]},
                        )
                    return "continue"

                duplicate_tool_rounds += 1
                log_activity(
                    "tool.duplicate",
                    "Suppressed duplicate tool call output",
                    {"tools": [call.tool for call in tool_calls]},
                )

                if last_successful_tool_result is not None:
                    if not emit_synthesis_from_last_successful_tool("duplicate tool call after successful tool result"):
                        emit_text(fallback_answer_from_last_successful_tool())
                    return "stop"

                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Those tool calls were already queued or executed. Choose different valid tool calls if needed, "
                            "or answer the user normally."
                        ),
                    }
                )
                if duplicate_tool_rounds >= 2:
                    recover_stuck_loop("duplicate_tool_call", tools=[call.tool for call in tool_calls], detail="duplicate parsed tool calls")
                    return "stop"
                return "continue"

            def run_memory_broker_after_turn(assistant_answer: str) -> None:
                """Run one narrow backend memory-broker pass after the visible answer.

                The assistant model owns the conversation. After it finishes, the
                runtime may save one compact durable project note from completed
                tool results. This is intentionally deterministic now: no hidden
                second model decides what the conversation "really" meant.
                """
                if not successful_tool_results:
                    return

                write_count = 0
                for source_result in reversed(successful_tool_results):
                    throw_if_cancelled()
                    broker_call = project_memory_broker_call(
                        chat_id=run.chat_id,
                        latest_user_text=latest_user_message(messages),
                        assistant_answer=assistant_answer,
                        tool_result=source_result,
                        should_cancel=run.cancel_requested.is_set,
                    )

                    if broker_call is None:
                        continue

                    if broker_call.tool != "record_project_memory":
                        log_activity(
                            "memory_broker.rejected_tool",
                            "Rejected non-project-memory broker call",
                            {"tool": broker_call.tool},
                        )
                        return

                    broker_call = ToolCall(
                        tool=broker_call.tool,
                        arguments={**broker_call.arguments, "conversation_id": run.chat_id},
                    )
                    arguments_summary = summarize_arguments(broker_call.arguments)
                    category = str(broker_call.arguments.get("category", "")).strip()
                    if category:
                        arguments_summary["category"] = category

                    tool_event = create_runtime_tool_event(
                        run.chat_id,
                        broker_call.tool,
                        arguments_summary,
                        "Memory updated: saving a compact project note...",
                        mode=run.mode,
                    )
                    broadcast_tool_event("tool_call", tool_event)

                    log_activity(
                        "memory_broker.started",
                        "Project memory broker started memory write",
                        {"tool": broker_call.tool, "arguments_summary": arguments_summary},
                    )

                    result = executor.execute(broker_call)

                    try:
                        event_id = int(tool_event.get("id", 0))
                    except (TypeError, ValueError):
                        event_id = 0

                    status = "completed" if result.ok else "error"
                    updated_event = update_runtime_tool_event(
                        event_id,
                        status,
                        result.summary,
						{
							"tool": result.tool,
							"arguments_summary": result.arguments_summary,
							"result_summary": result.summary if result.ok else "",
							"result_content": result.content if result.ok else "",
							"error": result.error if not result.ok else "",
							"truncated": result.truncated,
							"raw_result_visible": False,
							"memory_broker": True,
							"auto_memory_update": True,
							**(result.metadata or {}),
						},
					)
                    broadcast_tool_event("tool_result" if result.ok else "tool_error", updated_event)

                    log_activity(
                        "memory_broker.succeeded" if result.ok else "memory_broker.failed",
                        ("Completed" if result.ok else "Failed") + " project memory broker write",
                        {
                            "tool": result.tool,
                            "arguments_summary": result.arguments_summary,
                            "error": result.error if not result.ok else "",
                        },
                    )
                    if not result.ok:
                        return

                    write_count += 1
                    if write_count >= MAX_AUTOMATIC_MEMORY_WRITES:
                        return

            while True:
                throw_if_cancelled()

                response: CollectedResponse | None = None
                response_text = ""

                if not pending_tool_calls:
                    response = collect_response(
                        messages,
                        live=False,
                        live_thinking=True,
                        thinking_phase="model_decision",
                        prompt_label="normal_chat",
                    )
                    # Strip any system-reminder blocks that leaked into the response
                    response_text = _strip_system_reminders(response.response_text)

                    # Native function calls take priority: when the provider emits
                    # structured tool calls we execute them directly and skip the
                    # entire text-protocol recovery machinery below (which exists
                    # only to salvage prose-wrapped/malformed text tool calls).
                    if response.tool_calls:
                        action = handle_parsed_tool_calls(response.tool_calls)
                        if action == "continue":
                            continue
                        if action == "stop":
                            break

                    # Try tool call parsing. If it *looks* like a tool call but
                    # is malformed or mixed with prose, do not leak it into the
                    # chat. Keep it internal and recover where safe. After a
                    # successful tool result, malformed tool-looking output
                    # should turn into a final-answer retry, not a user-visible stop.
                    try:
                        tool_calls = parse_tool_calls(response_text)
                        action = handle_parsed_tool_calls(tool_calls)
                        if action == "continue":
                            continue
                        if action == "stop":
                            break
                    except ToolParseError as error:
                        if contains_tool_call(response_text):
                            recovery_error: ToolParseError | None = None
                            try:
                                tool_calls = parse_tool_call_lines(response_text)
                                action = handle_parsed_tool_calls(tool_calls, recovered_from_prose=True)
                                if action == "continue":
                                    continue
                                if action == "stop":
                                    break
                            except ToolParseError as extracted_error:
                                recovery_error = extracted_error

                            shown_error = recovery_error or error
                            malformed_tool_rounds += 1
                            log_activity(
                                "tool.malformed",
                                "Blocked malformed tool call output",
                                {"error": str(shown_error), "response": response_text[:500]},
                            )

                            if last_successful_tool_result is not None:
                                if not emit_synthesis_from_last_successful_tool("malformed tool call after successful tool result"):
                                    emit_text(fallback_answer_from_last_successful_tool())
                                break

                            if malformed_tool_rounds >= 2:
                                recover_stuck_loop("malformed_tool_call", detail=str(shown_error))
                                break

                            messages.append(
                                {
                                    "role": "system",
                                    "content": (
                                        "Your previous response looked like a tool call, but it was malformed and was not shown to the user.\n"
                                        f"Parser error: {shown_error}\n"
                                        "If you need tools, output one or more valid `tool_call: {...}` JSON lines, for example:\n"
                                        'tool_call: {"name": "read_file", "arguments": {"file_path": "README.md", "project_id": "stasis-c3804eb0"}}\n'
                                        "Do not use XML or shorthand like `tool_call: read_file`."
                                    ),
                                }
                            )
                            continue

                    if response.response_emitted:
                        break

                    # Check for unsupported tool syntax patterns
                    if response_uses_unsupported_tool_syntax(response_text):
                        unsupported_tool_rounds += 1

                        if last_successful_tool_result is not None:
                            log_activity(
                                "tool.unsupported_after_result",
                                "Suppressed unsupported tool-like output after successful tool result",
                                {"response": response_text[:500]},
                            )
                            if not emit_synthesis_from_last_successful_tool("unsupported tool syntax after successful tool result"):
                                emit_text(fallback_answer_from_last_successful_tool())
                            break

                        tool_protocol_error_event(
                            "Blocked unsupported tool syntax.",
                            "The model output malformed or unsupported tool syntax. Use the regular tool_call: {...} prefix with valid JSON.",
                        )

                        if unsupported_tool_rounds >= 2:
                            recover_stuck_loop("unsupported_tool_syntax", detail=response_text[:500])
                            break

                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Your previous response used malformed or unsupported tool syntax. "
                                    "Use one or more `tool_call: {...}` JSON lines with valid JSON and no prose around them.\n"
                                    "\n"
                                    "Correct:\n"
                                    'tool_call: {"name": "read_file", "arguments": {"file_path": "README.md", "project_id": "stasis-c3804eb0"}}\n'
                                    "\n"
                                    "Compatibility notes:\n"
                                    '- Prefer "name", but legacy "tool" and "type" are tolerated\n'
                                    '- Prefer nested "arguments", but simple top-level args are tolerated\n'
                                    '- Prefer "file_path", but legacy "path" is tolerated for read_file\n'
                                    "- Do not use XML, function call syntax, or prose transcripts"
                                ),
                            }
                        )
                        continue

                    if should_repair_unbacked_artifact_response(
                        initial_latest_user_text,
                        response_text,
                        all_successful_tool_results,
                    ):
                        artifact_creation_repair_rounds += 1
                        log_activity(
                            "artifact.unbacked_claim_blocked",
                            "Blocked response that claimed or implied file creation without a file-writing tool",
                            {"attempt": artifact_creation_repair_rounds, "response": response_text[:500]},
                        )
                        if artifact_creation_repair_rounds >= 2:
                            salvaged = salvage_authored_content(response_text)
                            if salvaged is not None:
                                title, body = salvaged
                                try:
                                    document = write_workspace_document(
                                        "drafts",
                                        title,
                                        body,
                                        summary="Salvaged from a chat reply that authored content without running a file-writing tool.",
                                        source="chat_salvage",
                                    )
                                    log_activity(
                                        "artifact.salvaged",
                                        "Saved authored content to workspace after unbacked file claim",
                                        {"rel_path": document.rel_path, "title": document.title},
                                    )
                                    emit_text(
                                        f"I drafted that but didn't run the file tool, so I saved it to my workspace as **{document.title}** (`{document.rel_path}`) so it isn't lost. "
                                        "Want me to write it to a specific file or project instead?"
                                    )
                                    break
                                except Exception as salvage_error:
                                    log_activity(
                                        "artifact.salvage_failed",
                                        "Workspace salvage write failed",
                                        {"error": str(salvage_error)},
                                    )
                            emit_text(
                                "I should create that as an actual file, but the model did not issue a file-writing tool call. Please try again and I’ll use the artifact tools."
                            )
                            break
                        messages.append(artifact_creation_repair_message(initial_latest_user_text, response_text))
                        continue

                    if post_result_response_is_nonsense(response_text, last_successful_tool_result):
                        recover_stuck_loop("post_result_nonsense", detail=response_text[:500])
                        break

                    emit_collected_response(response)
                    break

                if tool_rounds >= max_tool_rounds:
                    record_loop_incident(
                        provider=config.provider.type,
                        model=run.model or config.provider.model,
                        mode=run.mode,
                        reason="tool_round_limit",
                        tools=[result.tool for result in all_successful_tool_results[-4:]],
                        recovery="synthesize_from_completed_results",
                        chat_id=run.chat_id,
                        run_id=run.run_id,
                        metadata={"tool_rounds": tool_rounds, "max_tool_rounds": max_tool_rounds},
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The tool-call round limit was reached. Tools are now disabled for this turn. "
                                "Answer the user from the tool results already present above, or ask a concise clarification. "
                                "Do not output another tool call."
                            ),
                        }
                    )

                    final_response = collect_response(
                        messages,
                        live=True,
                        live_thinking=False,
                        prompt_label="tool_limit_final",
                        allow_tools=False,
                    )
                    final_text = final_response.response_text

                    if (
                        not final_response.response_emitted
                        and (
                            contains_tool_call(final_text)
                            or response_uses_unsupported_tool_syntax(final_text)
                        )
                    ):
                        if not emit_synthesis_from_last_successful_tool("tool round limit reached"):
                            emit_text(fallback_answer_from_last_successful_tool())
                    else:
                        emit_collected_response(final_response)

                    break

                try:
                    throw_if_cancelled()
                    tool_announcement = ""
                    current_tool_call: ToolCall | None = None
                    tool_call = pending_tool_calls.pop(0) if pending_tool_calls else parse_tool_call(response_text)
                    current_tool_call = tool_call
                    missing_arguments = missing_required_arguments(tool_call)
                    if suppress_incomplete_tool_after_success(tool_call, missing_arguments):
                        if malformed_tool_rounds >= 2:
                            break
                        continue

                    if missing_arguments:
                        raise ToolParseError(
                            "Tool call is missing required argument(s): " + ", ".join(missing_arguments)
                        )

                    signature = tool_signature(tool_call)
                    effect_key = tool_effect_key(tool_call)

                    if signature in called_tools_signatures or (effect_key is not None and effect_key in called_tool_effect_keys):
                        duplicate_tool_rounds += 1
                        log_activity(
                            "tool.duplicate",
                            "Suppressed duplicate tool call output",
                            {"tool": tool_call.tool, "arguments": summarize_arguments(tool_call.arguments), "effect_key": effect_key or ""},
                        )

                        if last_successful_tool_result is not None:
                            if not emit_synthesis_from_last_successful_tool("duplicate tool call after successful tool result"):
                                emit_text(fallback_answer_from_last_successful_tool())
                            break

                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "This tool call was already executed in this conversation. "
                                    "Do not repeat the same tool call. Use the existing result or choose a different action."
                                ),
                            }
                        )
                        if duplicate_tool_rounds >= 2:
                            recover_stuck_loop("duplicate_tool_call", tools=[tool_call.tool], detail="duplicate executable tool call")
                            break
                        continue

                    called_tools_signatures.add(signature)
                    if effect_key is not None:
                        called_tool_effect_keys.add(effect_key)

                    # Inject conversation_id into memory tool arguments
                    if tool_call.tool in {"record_episode", "update_episode", "forget_episode", "record_project_memory", "update_project_memory", "record_memory", "write_memory", "update_memory", "archive_memory", "move_memory", "merge_memory"}:
                        tool_call = ToolCall(
                            tool=tool_call.tool,
                            arguments={**tool_call.arguments, "conversation_id": run.chat_id},
                        )

                    tool_announcement = tool_call_announcement(tool_call)
                    thinking_status = tool_call_thinking(tool_call)
                    if thinking_status:
                        emit_thinking_text(thinking_status)
                    if tool_announcement:
                        emit_text(tool_announcement + "\n")

                    arguments_summary = {
                        key: value
                        for key, value in tool_call.arguments.items()
                        if key in {"episode_id", "title_query", "title", "project_id", "file_path", "command", "app_id", "window_id", "name", "selector", "role", "text"}
                    }

                    tool_event = create_runtime_tool_event(
                        run.chat_id,
                        tool_call.tool,
                        arguments_summary,
                        f"Running {tool_call.tool}...",
                        mode=run.mode,
                    )
                    broadcast_tool_event("tool_call", tool_event)

                    log_activity(
                        "tool.started",
                        f"Started tool {tool_call.tool}",
                        {"tool": tool_call.tool, "arguments_summary": arguments_summary},
                    )

                    throw_if_cancelled()

                    if tool_call.tool == "request_user_input":
                        request = parse_question_request(tool_call.arguments)
                        with run.lock:
                            run.question_request = request
                            run.question_answers = {}
                            run.question_response.clear()
                        run.broadcast({"kind": "question_request", "request": question_request_to_json(request)})
                        log_activity(
                            "question.requested",
                            "Paused chat for user input",
                            {"chat_id": run.chat_id, "interaction_id": request.id, "question_count": len(request.questions)},
                        )
                        while not run.question_response.is_set():
                            if run.cancel_requested.is_set():
                                raise ChatCancelled()
                            run.question_response.wait(timeout=0.25)
                        result = ToolResult(
                            tool="request_user_input",
                            ok=True,
                            content=question_answers_tool_result(request, run.question_answers),
                            summary="User answered the requested questions.",
                            arguments_summary={"interaction_id": request.id, "question_count": len(request.questions)},
                        )
                        with run.lock:
                            run.question_request = None
                            run.question_answers = {}
                        run.broadcast({"kind": "question_answered", "interaction_id": request.id})
                    else:
                        result = None

                    mode_error = executor.check_mode_restrictions(tool_call) if result is None else ""
                    if mode_error and result is None:
                        result = ToolResult(
                            tool=tool_call.tool,
                            ok=False,
                            content="",
                            summary=f"Blocked in {executor.mode} mode",
                            arguments_summary=summarize_arguments(tool_call.arguments),
                            error=mode_error,
                        )
                        throw_if_cancelled()
                    elif result is None:
                        result = None

                    # Permission check. Mode boundaries are enforced first so Plan mode never asks
                    # for permission to perform a write/delete operation it cannot run.
                    if result is None:
                        required, reason = needs_permission(tool_call, registry.definition(tool_call.tool))
                    else:
                        required, reason = False, ""
                    if required:
                        log_activity(
                            "tool.permission_requested",
                            f"Permission required for {tool_call.tool}: {reason}",
                            {"tool": tool_call.tool, "reason": reason, "arguments": tool_call.arguments},
                        )

                        with run.lock:
                            run.permission_request = {"tool": tool_call.tool, "reason": reason, "arguments": tool_call.arguments}
                            run.permission_response.clear()
                            run.permission_granted = False

                        run.broadcast(
                            {
                                "kind": "permission_request",
                                "tool": tool_call.tool,
                                "reason": reason,
                                "arguments": tool_call.arguments,
                            }
                        )

                        # Wait for response from user (via /chat/permission endpoint)
                        while not run.permission_response.is_set():
                            if run.cancel_requested.is_set():
                                raise ChatCancelled()
                            run.permission_response.wait(timeout=0.25)

                        if not run.permission_granted:
                            # User denied permission - as per instructions, cancel the connection
                            log_activity(
                                "tool.permission_denied",
                                f"User denied permission for {tool_call.tool}",
                                {"tool": tool_call.tool, "reason": reason},
                            )
                            raise ChatCancelled()

                        # Permission granted, clear it and proceed
                        log_activity(
                            "tool.permission_granted",
                            f"Permission granted for {tool_call.tool}",
                            {"tool": tool_call.tool, "arguments": tool_call.arguments},
                        )
                        grant_approved_tool_permission(tool_call.tool)

                        with run.lock:
                            run.permission_request = None

                    if result is None:
                        throw_if_cancelled()
                        result = executor.execute(tool_call)
                        throw_if_cancelled()

                    if result.arguments_summary:
                        arguments_summary = result.arguments_summary
                except ToolParseError as error:
                    malformed_tool_rounds += 1
                    if malformed_tool_rounds >= 2:
                        recover_stuck_loop("missing_required_args", detail=str(error))
                        break
                    result = invalid_tool_result(str(error))
                    tool_event = create_runtime_tool_event(run.chat_id, result.tool, {}, "Invalid tool call.", mode=run.mode)
                    broadcast_tool_event("tool_call", tool_event)

                status = "completed" if result.ok else "error"

                try:
                    event_id = int(tool_event.get("id", 0))
                except (TypeError, ValueError):
                    event_id = 0

                updated_event = update_runtime_tool_event(
                    event_id,
                    status,
                    result.summary,
					{
						"tool": result.tool,
						"arguments_summary": result.arguments_summary,
						"result_summary": result.summary if result.ok else "",
						"result_content": result.content if result.ok else "",
						"error": result.error if not result.ok else "",
						"truncated": result.truncated,
						"raw_result_visible": False,
						**(result.metadata or {}),
					},
				)
                broadcast_tool_event("tool_result" if result.ok else "tool_error", updated_event)
                if current_tool_call is not None:
                    try:
                        record_coding_tool_result(current_tool_call, result)
                    except Exception as coding_error:
                        log_activity(
                            "coding_run.record_failed",
                            "Failed to record coding-run tool step",
                            {"tool": result.tool, "error": str(coding_error)},
                        )

                log_activity(
                    "tool.succeeded" if result.ok else "tool.failed",
                    ("Completed" if result.ok else "Failed") + f" tool {result.tool}",
                    {
                        "tool": result.tool,
                        "arguments_summary": result.arguments_summary,
                        "error": result.error if not result.ok else "",
                    },
                )

                if result.ok:
                    all_successful_tool_results.append(result)
                    record_continuity_event(
                        "tool_run_completed",
                        f"Tool {result.tool} completed: {result.summary}",
                        source="chat",
                        chat_id=run.chat_id,
                        run_id=run.run_id,
                        project_id=str(result.arguments_summary.get("project_id") or "") if isinstance(result.arguments_summary, dict) else "",
                        metadata={"tool": result.tool, "arguments_summary": result.arguments_summary},
                    )
                    try:
                        remember_tool_result_context(run.chat_id, result)
                    except Exception as cache_error:
                        log_activity(
                            "tool.cache_failed",
                            "Failed to cache successful tool result for follow-up context",
                            {"tool": result.tool, "error": str(cache_error)},
                        )

                    last_successful_tool_result = result
                    if result.tool not in {"record_episode", "update_episode", "forget_episode", "record_project_memory", "update_project_memory", "record_memory", "write_memory", "update_memory", "archive_memory", "move_memory", "merge_memory"}:
                        successful_tool_results.append(result)
                    malformed_tool_rounds = 0
                    unsupported_tool_rounds = 0
                    duplicate_tool_rounds = 0

                # Append only meaningful assistant text. Tool cards carry progress,
                # so most tool calls no longer create a chat preamble.
                if tool_announcement:
                    messages.append({"role": "assistant", "content": tool_announcement})

                # Append the tool result as a system message
                messages.append(result.to_model_message())

                # Carry the model's own plan forward so the next round continues
                # the task instead of re-deriving it. Replace any prior note so it
                # does not accumulate, and keep it at the end where local chat
                # templates include it most reliably.
                plan_note = working_plan_note(run.thinking_text)
                if plan_note is not None:
                    messages[:] = [message for message in messages if not message.get(WORKING_PLAN_MARKER)]
                    messages.append(plan_note)

                # Finish the current assistant turn before next model call
                finish_current_assistant_turn()

                # Increment tool rounds and continue — model decides next step
                tool_rounds += 1

            throw_if_cancelled()
            persist(force=True)

            if run.assistant_text.strip():
                active_project_id = active_project_from_tool_results(successful_tool_results)
                capture_post_chat_episodic_fallback(
                    chat_id=run.chat_id,
                    run_id=run.run_id,
                    latest_user_text=initial_latest_user_text,
                    assistant_text=run.assistant_text,
                    tool_results=all_successful_tool_results,
                    project_id=active_project_id,
                )

            if run.assistant_text.strip() and not run.return_greeting_text.strip():
                try:
                    intention = select_surfaceable_intention(
                        chat_id=run.chat_id,
                        latest_user_text=initial_latest_user_text,
                        response_text=run.assistant_text,
                        active_project_id=active_project_id,
                        mode=run.mode,
                        quiet_mode=lifecycle_quiet_mode(),
                    )
                    if intention is not None:
                        emit_text(surfaced_intention_text(intention))
                        mark_intention_surfaced(run.chat_id, intention, run.run_id)
                        record_continuity_event(
                            "intention_shown",
                            f"Surfaced queued {intention.kind}: {intention.content}",
                            source="chat",
                            chat_id=run.chat_id,
                            run_id=run.run_id,
                            project_id=str(intention.metadata.get("project_id") or "") if isinstance(intention.metadata, dict) else "",
                            metadata={"intention_id": intention.id, "kind": intention.kind},
                        )
                        log_activity(
                            "intention.surfaced",
                            "Surfaced queued question/comment after assistant response",
                            {"chat_id": run.chat_id, "run_id": run.run_id, "intention_id": intention.id, "kind": intention.kind},
                        )
                except Exception as error:
                    log_activity(
                        "intention.surface_failed",
                        "Failed to surface queued question/comment after assistant response",
                        {"chat_id": run.chat_id, "run_id": run.run_id, "error": str(error)},
                    )

            if run.assistant_text.strip():
                schedule_memory_consolidation(run.chat_id, model=run.model)

            if coding_run is not None:
                try:
                    record_coding_run_step(
                        coding_run.id,
                        phase="summarize",
                        kind="runtime",
                        status="completed",
                        summary=(run.assistant_text.strip()[:1000] or "Final response prepared."),
                    )
                    complete_coding_run(coding_run.id, summary=run.assistant_text.strip()[:2000])
                    log_activity(
                        "coding_run.completed",
                        "Completed coding work loop",
                        {"coding_run_id": coding_run.id, "chat_id": run.chat_id},
                    )
                except Exception as coding_error:
                    log_activity(
                        "coding_run.complete_failed",
                        "Failed to complete coding work loop",
                        {"coding_run_id": coding_run.id, "error": str(coding_error)},
                    )

            with run.lock:
                run.status = "complete"

            run.broadcast({"done": True})
        except ChatCancelled:
            persist(force=True)
            if coding_run is not None:
                try:
                    complete_coding_run(coding_run.id, status="failed", summary="Coding run cancelled.")
                except Exception:
                    pass

            with run.lock:
                run.status = "cancelled"

            run.broadcast({"kind": "cancelled", "text": "Stopped.", "done": True})
        except Exception as error:
            persist(force=True)
            if coding_run is not None:
                try:
                    complete_coding_run(coding_run.id, status="failed", summary=str(error))
                except Exception:
                    pass

            with run.lock:
                run.status = "failed"
                run.error = str(error)

            run.broadcast({"kind": "error", "text": str(error), "done": True})
        finally:
            unregister_chat_run(run.chat_id, run)

    run.thread = threading.Thread(target=generate, name=f"bitbuddy-chat-run-{run.chat_id}", daemon=True)
    run.thread.start()


def grant_approved_tool_permission(tool_name: str) -> None:
    calendar_scopes = {
        "calendar_view_events": "read",
        "calendar_find_free_time": "read",
        "calendar_create_event": "create",
        "calendar_modify_event": "modify",
        "calendar_delete_event": "delete",
    }
    email_scopes = {
        "email_list_mailboxes": "read",
        "email_recent_messages": "read",
        "email_read_message": "read",
        "email_search_messages": "search",
        "email_trash_message": "trash",
        "email_create_auto_trash_rule": "trash",
    }
    scope = calendar_scopes.get(tool_name)
    if not scope:
        email_scope = email_scopes.get(tool_name)
        if not email_scope:
            return
        try:
            from ..email.permissions import set_permission
            from ..email.service import email_account_id

            set_permission(email_account_id(), email_scope, "granted")
        except Exception as error:
            log_activity(
                "tool.permission_grant_failed",
                f"Failed to persist approved permission for {tool_name}: {error}",
                {"tool": tool_name, "scope": email_scope, "error": str(error)},
            )
        return
    try:
        from ..calendar.permissions import set_permission
        from ..calendar.service import user_timezone
        from ..calendar.store import ensure_default_calendar

        account, _calendar = ensure_default_calendar(user_timezone())
        set_permission(account.id, scope, "granted")
    except Exception as error:
        log_activity(
            "tool.permission_grant_failed",
            f"Failed to persist approved permission for {tool_name}: {error}",
            {"tool": tool_name, "scope": scope, "error": str(error)},
        )


def active_project_from_tool_results(results: list[ToolResult]) -> str:
    for result in reversed(results):
        project_id = result.arguments_summary.get("project_id") if isinstance(result.arguments_summary, dict) else None
        if isinstance(project_id, str) and project_id.strip():
            return project_id.strip()
    return ""
