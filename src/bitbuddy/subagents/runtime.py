from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs
from ..providers import ProviderClient
from ..toolbox.base import READ_ONLY_TOOLS, ToolCall, ToolExecutor, ToolParseError, ToolRegistry, ToolResult, is_mcp_read_only_tool, parse_tool_calls, tool_instruction_message
from ..utils import log_activity


DEFAULT_SUBAGENT_TOOLS = {
    "glob_files",
    "list_directory",
    "search_text",
    "read_file",
    "read_file_range",
    "get_project_brief",
    "get_project_memory",
    "web_search",
    "web_fetch",
    "calendar_view_events",
    "calendar_find_free_time",
    "email_list_mailboxes",
    "email_recent_messages",
    "email_search_messages",
    "email_read_message",
}
SUBAGENT_UNSAFE_READ_ONLY_TOOLS = {"run_shell_command", "run_subagent"}
SUBAGENT_SAFE_BUILTIN_TOOLS = READ_ONLY_TOOLS - SUBAGENT_UNSAFE_READ_ONLY_TOOLS


@dataclass(frozen=True)
class SubagentRunResult:
    run_id: str
    status: str
    report: str
    tool_results: list[ToolResult]
    error: str = ""


def ensure_subagent_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists subagent_runs (
                id text primary key,
                agent_type text not null default 'general',
                task text not null,
                status text not null,
                created_at text default current_timestamp,
                completed_at text,
                report text not null default '',
                error text not null default '',
                metadata text not null default '{}'
            )
            """
        )
        connection.execute(
            """
            create table if not exists subagent_steps (
                id integer primary key autoincrement,
                run_id text not null,
                sequence integer not null,
                tool text not null,
                status text not null,
                summary text not null default '',
                metadata text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )


def run_subagent(
    *,
    task: str,
    agent_type: str,
    registry: ToolRegistry,
    client: ProviderClient,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    project_id: str = "",
    max_rounds: int = 4,
) -> SubagentRunResult:
    ensure_subagent_database()
    run_id = str(uuid.uuid4())
    clean_task = task.strip()
    clean_agent_type = (agent_type or "general").strip() or "general"
    allowed = selected_tool_names(registry, allowed_tools)
    sub_registry = filtered_registry(registry, allowed)
    executor = ToolExecutor(sub_registry, mode="chat", mode_context=clean_task)
    insert_run(run_id, clean_agent_type, clean_task, {"allowed_tools": sorted(allowed), "project_id": project_id})
    log_activity("subagent.started", "Started subagent run", {"run_id": run_id, "agent_type": clean_agent_type, "task": clean_task[:300]})

    messages = [
        {
            "role": "system",
            "content": "\n\n".join(
                [
                    f"You are a private {clean_agent_type} subagent working for the parent assistant.",
                    "Complete the delegated task using the available tools when useful. Keep all scratch work private.",
                    "Return a concise final report for the parent assistant. Include findings, files inspected, changes made if any, and residual risks.",
                    "Do not ask the user questions. If blocked, report the blocker clearly.",
                    tool_instruction_message(sub_registry)["content"],
                ]
            ),
        },
        {"role": "user", "content": f"Task: {clean_task}\nProject id: {project_id or '(none)'}"},
    ]

    tool_results: list[ToolResult] = []
    try:
        for round_index in range(max(1, min(8, max_rounds))):
            text = collect_response(client, messages, model=model)
            try:
                calls = parse_tool_calls(text)
            except ToolParseError:
                complete_run(run_id, "completed", text, "")
                log_activity("subagent.completed", "Completed subagent run", {"run_id": run_id, "rounds": round_index})
                return SubagentRunResult(run_id, "completed", text, tool_results)

            if not calls:
                complete_run(run_id, "completed", text, "")
                return SubagentRunResult(run_id, "completed", text, tool_results)

            for call in calls:
                if call.tool not in allowed:
                    result = ToolResult(call.tool, False, "", "Subagent tool not allowed", {"tool": call.tool}, error=f"Tool `{call.tool}` is not allowed for this subagent run.")
                else:
                    result = executor.execute(ToolCall(call.tool, default_project_arguments(call.arguments, project_id)))
                tool_results.append(result)
                insert_step(run_id, len(tool_results), result)
                messages.append(result.to_model_message())

        final_prompt = {"role": "system", "content": "Tool round limit reached. Return the best concise final report now. Do not call tools."}
        report = collect_response(client, [*messages, final_prompt], model=model)
        complete_run(run_id, "completed", report, "")
        return SubagentRunResult(run_id, "completed", report, tool_results)
    except Exception as error:
        complete_run(run_id, "failed", "", str(error))
        log_activity("subagent.failed", "Subagent run failed", {"run_id": run_id, "error": str(error)})
        return SubagentRunResult(run_id, "failed", "", tool_results, error=str(error))


def selected_tool_names(registry: ToolRegistry, requested: list[str] | None) -> set[str]:
    available = {definition.name for definition in registry.definitions() if definition.name != "run_subagent"}
    if not requested:
        names = available.intersection(DEFAULT_SUBAGENT_TOOLS)
    else:
        names = {name for name in requested if name in available and name != "run_subagent"}
    return {name for name in names if is_subagent_safe_tool(registry.definition(name), name)}


def is_subagent_safe_tool(definition: Any, tool_name: str) -> bool:
    if is_desktop_control_tool(definition, tool_name):
        return False
    if is_mcp_read_only_tool(definition):
        return True
    return tool_name in SUBAGENT_SAFE_BUILTIN_TOOLS


def filtered_registry(registry: ToolRegistry, allowed: set[str]) -> ToolRegistry:
    result = ToolRegistry()
    for name in sorted(allowed):
        definition = registry.definition(name)
        handler = registry.handler(name)
        if definition is not None and handler is not None:
            result.register(definition, handler)
    return result


def is_desktop_control_tool(definition: Any, tool_name: str = "") -> bool:
    annotations = getattr(definition, "annotations", None)
    if isinstance(annotations, dict) and str(annotations.get("mcp_server") or "") == "computer_use_linux":
        return True
    return str(tool_name or "").startswith("mcp_computer_use_linux_")


def default_project_arguments(arguments: dict[str, object], project_id: str) -> dict[str, object]:
    if not project_id or "project_id" in arguments:
        return arguments
    return {**arguments, "project_id": project_id}


def collect_response(client: ProviderClient, messages: list[dict[str, str]], model: str | None) -> str:
    parts: list[str] = []
    for chunk in client.stream_chat(messages, model=model):
        if chunk.kind == "response":
            parts.append(chunk.text)
    return "".join(parts).strip()


def insert_run(run_id: str, agent_type: str, task: str, metadata: dict[str, Any]) -> None:
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "insert into subagent_runs (id, agent_type, task, status, metadata) values (?, ?, ?, 'running', ?)",
            (run_id, agent_type, task, json.dumps(metadata)),
        )


def complete_run(run_id: str, status: str, report: str, error: str) -> None:
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "update subagent_runs set status = ?, completed_at = current_timestamp, report = ?, error = ? where id = ?",
            (status, report[:12000], error[:2000], run_id),
        )


def insert_step(run_id: str, sequence: int, result: ToolResult) -> None:
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "insert into subagent_steps (run_id, sequence, tool, status, summary, metadata) values (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                sequence,
                result.tool,
                "completed" if result.ok else "error",
                result.summary[:1000],
                json.dumps({"arguments_summary": result.arguments_summary, "error": result.error, "truncated": result.truncated}),
            ),
        )
