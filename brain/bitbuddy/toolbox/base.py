from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..memory.layers import layer_catalog
from ..paths import ARTIFACTS_DIR, WORKSPACE_DIR

TOOL_CALL_PREFIX = "tool_call:"
XML_TOOL_CALL_TAGS = ("bitbuddy_tool_call", "tool_call")
MAX_TOOL_PAYLOAD_CHARS = 4000
SHELL_READ_COMMANDS = {"cat", "less", "head", "tail"}
READ_ONLY_TOOLS = {
    "glob_files",
    "list_directory",
    "search_text",
    "web_search",
    "web_fetch",
    "get_project_memory",
    "get_project_brief",
    "search_memory",
    "list_memory",
    "read_file",
    "read_file_range",
    "run_shell_command",
    "run_subagent",
    "list_skills",
    "load_skill",
    "validate_skill",
    "calendar_view_events",
    "calendar_find_free_time",
    "email_list_mailboxes",
    "email_recent_messages",
    "email_search_messages",
    "email_read_message",
}
FILE_WRITE_TOOLS = {
    "write_file",
    "patch_file",
    "make_directory",
}
CALENDAR_TOOL_SCOPES = {
    "calendar_view_events": "read",
    "calendar_find_free_time": "read",
    "calendar_create_event": "create",
    "calendar_modify_event": "modify",
    "calendar_delete_event": "delete",
}
EMAIL_TOOL_SCOPES = {
    "email_list_mailboxes": "read",
    "email_recent_messages": "read",
    "email_read_message": "read",
    "email_search_messages": "search",
    "email_trash_message": "trash",
    "email_create_auto_trash_rule": "trash",
}
MEMORY_WRITE_TOOLS = {
    "record_episode",
    "update_episode",
    "forget_episode",
    "record_project_memory",
    "update_project_memory",
    "record_memory",
    "write_memory",
    "update_memory",
    "archive_memory",
    "move_memory",
    "merge_memory",
    "create_skill",
    "patch_skill",
    "archive_skill",
    "write_skill_file",
    *FILE_WRITE_TOOLS,
}
DEBUG_RELATED_KEYWORDS = {
    "assert",
    "bug",
    "broken",
    "crash",
    "debug",
    "defect",
    "diagnose",
    "error",
    "exception",
    "fail",
    "failing",
    "failure",
    "fix",
    "issue",
    "lint",
    "problem",
    "pytest",
    "regression",
    "repair",
    "reproduce",
    "root cause",
    "stack trace",
    "test",
    "traceback",
    "typecheck",
}
UNSUPPORTED_TOOL_MARKERS = (
    "<tool_call>",
    "</tool_call>",
    "<bitbuddy_tool_call>",
    "</bitbuddy_tool_call>",
    "tool_use:default_api:",
    "<tool_code>",
    "</tool_code>",
    "DataReadTool",
    "read_file(",
    "get_project_brief(",
    "get_project_memory(",
    "run_shell_command(",
    "record_episode(",
    "update_episode(",
    "forget_episode(",
    "record_project_memory(",
    "update_project_memory(",
    "record_memory(",
    "write_memory(",
    "search_memory(",
    "update_memory(",
    "archive_memory(",
    "list_memory(",
    "move_memory(",
    "merge_memory(",
    "list_skills(",
    "load_skill(",
    "create_skill(",
    "patch_skill(",
    "archive_skill(",
    "write_skill_file(",
    "write_file(",
    "patch_file(",
    "make_directory(",
    "validate_skill(",
    "list_projects(",
    "[Read File:",
    "[Write File:",
    "[Edit File:",
    "[Bash:",
    "[Shell:",
    "[Tool:",
    "[Tool Call]",
    "[BitBuddy]",
    "[bitbuddy]",
    "[Context]",
    "[Action]",
    "[Observation]",
    "[Thought]",
    "[Response]",
    "Tool Call:",
    "Action:",
    "Observation:",
    "Thought:",
    "Reading Files:",
    "Reading files:",
    "Reading File:",
    "Reading file:",
    "[read_file]",
    "[list_directory]",
    "[list_dir]",
    "<system-reminder>",
    "</system-reminder>",
    "Your operational mode has changed",
    "Arguments:",
    "Argument:",
    "arguments:",
    "argument:",
)


class ToolParseError(ValueError):
    pass


class ToolExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments_schema: dict[str, object]
    max_chars: int
    annotations: dict[str, object] | None = None


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolResult:
    tool: str
    ok: bool
    content: str
    summary: str
    arguments_summary: dict[str, object]
    truncated: bool = False
    error: str = ""
    metadata: dict[str, object] | None = None

    def to_model_message(self) -> dict[str, str]:
        """Return the completed tool result as provider-visible working context.

        This deliberately uses role='user' instead of a late system message.
        Some local chat-template backends only honor the first system message,
        which made models see the visible receipt ("Read README.md...") but not
        the actual file/tool payload.  A user-role working-context message is
        much more reliably included in the next model turn.
        """
        status = "success" if self.ok else "error"
        guidance = (
            "The tool has already run. Use the result content below as private working context. "
            "If it gives you enough information, answer the user's request normally. "
            "Call another tool only if it would genuinely help. Do not paste raw/full tool output "
            "unless the user explicitly asked to see raw/full output."
        )
        if self.tool == "read_file":
            guidance += (
                " For read_file specifically: the file text is included below. "
                "You have read it; answer from it. If the user asked what you learned, what it says, "
                "or for a summary/explanation, synthesize from the file content instead of only saying it was read."
            )

        lines = [
            "[Tool Result Working Context]",
            "This message is private working context for the assistant, not a new user request.",
            f"tool: {self.tool}",
            f"status: {status}",
            f"truncated: {str(self.truncated).lower()}",
            "",
            "result_content_private_working_context:",
            self.content if self.ok else self.error,
            "",
            guidance,
        ]
        return {"role": "user", "content": "\n".join(lines).strip()}


ToolHandler = Callable[[dict[str, object], ToolDefinition], ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def handler(self, name: str) -> ToolHandler | None:
        return self._handlers.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions)]


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, mode: str = "chat", mode_context: str = "") -> None:
        self.registry = registry
        self.mode = normalize_mode(mode)
        self.mode_context = mode_context

    def execute(self, call: ToolCall) -> ToolResult:
        definition = self.registry.definition(call.tool)
        handler = self.registry.handler(call.tool)
        arguments_summary = summarize_arguments(call.arguments)
        if definition is None or handler is None:
            return ToolResult(
                tool=call.tool,
                ok=False,
                content="",
                summary=f"Unknown tool: {call.tool}",
                arguments_summary=arguments_summary,
                error=f"Invalid tool call: unknown tool {call.tool!r}.",
            )

        # Mode-based restrictions
        mode_error = self.check_mode_restrictions(call)
        if mode_error:
            return ToolResult(
                tool=call.tool,
                ok=False,
                content="",
                summary=f"Blocked in {self.mode} mode",
                arguments_summary=arguments_summary,
                error=mode_error,
            )

        try:
            return handler(call.arguments, definition)
        except Exception as error:
            return ToolResult(
                tool=call.tool,
                ok=False,
                content="",
                summary=f"Tool failed: {call.tool}",
                arguments_summary=arguments_summary,
                error=str(error),
            )

    def check_mode_restrictions(self, call: ToolCall) -> str:
        """Return error message if tool is restricted in current mode, else empty string."""
        definition = self.registry.definition(call.tool)
        if is_mcp_read_only_tool(definition):
            return ""

        if self.mode == "plan":
            if call.tool != "run_shell_command" and call.tool not in READ_ONLY_TOOLS:
                return (
                    f"Plan mode is strictly read-only. Tool `{call.tool}` can write, create, update, archive, move, merge, or delete data, so it is blocked. "
                    "Use Chat for unrestricted changes or Debug for debugging-related changes."
                )

            if call.tool == "run_shell_command":
                command = str(call.arguments.get("command", "")).strip()
                if not is_plan_safe_command(command):
                    return (
                        "Plan mode is strictly read-only. "
                        f"The command `{command}` is not on the read-only allowlist or appears able to write, create, delete, install, test/build, or mutate state. "
                        "Use Chat for unrestricted commands or Debug for debugging-related changes."
                    )
        elif self.mode == "debug":
            if call.tool == "run_shell_command":
                command = str(call.arguments.get("command", "")).strip()
                if is_plan_safe_command(command):
                    return ""
            elif call.tool in READ_ONLY_TOOLS:
                return ""

            if not is_debug_related_call(call, self.mode_context):
                return (
                    f"Debug mode only allows write/create/update/archive/move/merge/delete operations when they are related to debugging. "
                    f"Tool `{call.tool}` was blocked because the tool call and current user request do not clearly indicate debugging work. "
                    "Use Chat for unrestricted changes, or make the debugging purpose explicit."
                )
        return ""


def normalize_mode(mode: str) -> str:
    clean = str(mode or "chat").strip().lower()
    return clean if clean in {"chat", "plan", "debug"} else "chat"


def is_mcp_tool_name(tool_name: str) -> bool:
    return str(tool_name or "").startswith("mcp_")


def tool_annotations(definition: ToolDefinition | None) -> dict[str, object]:
    if definition is None or not isinstance(definition.annotations, dict):
        return {}
    return definition.annotations


def is_mcp_read_only_tool(definition: ToolDefinition | None) -> bool:
    annotations = tool_annotations(definition)
    return bool(annotations.get("mcp")) and bool(annotations.get("readOnlyHint"))


def is_mcp_mutating_tool(definition: ToolDefinition | None, tool_name: str = "") -> bool:
    annotations = tool_annotations(definition)
    if not bool(annotations.get("mcp")) and not is_mcp_tool_name(tool_name):
        return False
    return not bool(annotations.get("readOnlyHint"))


def is_debug_related_call(call: ToolCall, mode_context: str = "") -> bool:
    text = " ".join(
        [
            call.tool,
            json.dumps(call.arguments, sort_keys=True, default=str),
            mode_context,
        ]
    ).lower()
    return any(keyword in text for keyword in DEBUG_RELATED_KEYWORDS)


def openai_tools_schema(registry: ToolRegistry, mode: str = "chat") -> list[dict[str, object]]:
    """Build an OpenAI-style tools array for native function calling.

    Each registered ToolDefinition becomes a {"type":"function","function":{...}}
    entry using its existing JSON-Schema arguments. In Plan mode only read-only
    tools are advertised so the model does not attempt writes the executor would
    block; the ToolExecutor still enforces all mode boundaries regardless.
    """
    normalized = normalize_mode(mode)
    tools: list[dict[str, object]] = []
    for definition in registry.definitions():
        if normalized == "plan" and definition.name not in READ_ONLY_TOOLS and not is_mcp_read_only_tool(definition):
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.arguments_schema,
                },
            }
        )
    return tools


def tool_instruction_message(registry: ToolRegistry, native_tools: bool = False) -> dict[str, str]:
    tool_lines = []
    for definition in registry.definitions():
        schema = json.dumps(definition.arguments_schema, sort_keys=True)
        tool_lines.append(f"- {definition.name}: {definition.description} Args: {schema}")
    layer_lines = [
        f"- {item['layer']}: {item['description']} Routing: {item['routing_rule']}"
        for item in layer_catalog()
    ]
    has_desktop_mcp = any(
        (definition.annotations or {}).get("mcp_server") == "computer_use_linux"
        for definition in registry.definitions()
    )
    desktop_lines = [
        "",
        "Desktop MCP guidance:",
        "- For computer-use-linux, start desktop-control sessions with the doctor tool when readiness is unknown.",
        "- Inspect windows/apps before targeted input; prefer get_app_state plus semantic element indices/selectors.",
        "- Prefer perform_action and set_value over coordinate clicks when accessibility exposes the control.",
        "- Use click, type_text, press_key, drag, and scroll only with explicit target/window context when possible.",
        "- After mutating desktop actions, verify state with get_app_state, focused_window, list_windows, or an app-specific readback.",
        "- Do not run desktop input tools concurrently; desktop control is stateful.",
    ] if has_desktop_mcp else []

    if native_tools:
        format_lines = [
            "Tool calling:",
            "- Tools are provided through the native function-calling interface. To use one, issue a real tool/function call — do not write tool calls as text in your reply.",
            "- Call a tool only when it genuinely helps; otherwise answer normally in plain prose.",
            "Tool results are working context. Do not paste raw tool/file output unless the user explicitly asks to see the full raw contents.",
            "When the user asks you to create/save/write/generate/export/update/edit/modify/tweak a file, you must actually call write_file/patch_file/make_directory (or a script + run_shell_command). Do not say 'saved to' or 'updated' or provide only a code block unless such a tool call actually succeeded.",
            "Do not invent tools. If asked to list tools, list only the exact tools in [Available Tools]; do not mention web browsing, external browsing, hidden tools, or permission behavior unless such a tool is actually listed.",
        ]
        example_lines: list[str] = []
    else:
        format_lines = [
            "Tool call format:",
            'tool_call: {"name": "TOOL_NAME", "arguments": {"ARG": "VALUE"}}',
            "",
            "When calling tools, output only one or more valid tool_call lines, one JSON object per line. Otherwise, respond normally.",
            "Tool results are working context. Do not paste raw tool/file output unless the user explicitly asks to see the full raw contents.",
            "When the user asks you to create/save/write/generate/export/update/edit/modify/tweak a file, you must use tools to create or change it. Do not say 'saved to' or 'updated' or provide only a code block unless a write_file/patch_file/make_directory or script+run_shell_command tool sequence actually succeeded.",
            "Do not invent tools. If asked to list tools, list only the exact tools in [Available Tools]; do not mention web browsing, external browsing, hidden tools, or permission behavior unless such a tool is actually listed.",
        ]
        example_lines = [
            "",
            "Useful examples:",
            'tool_call: {"name": "glob_files", "arguments": {"pattern": "**/*.py"}}',
            'tool_call: {"name": "search_text", "arguments": {"pattern": "class ToolExecutor", "include": "**/*.py"}}',
            'tool_call: {"name": "read_file", "arguments": {"project_id": "stasis-c3804eb0", "file_path": "README.md"}}',
            'tool_call: {"name": "run_shell_command", "arguments": {"command": "ls -la"}}',
            'tool_call: {"name": "write_file", "arguments": {"file_path": "kicad/demo.py", "content": "print(\"hello\")\\n"}}',
            'tool_call: {"name": "search_memory", "arguments": {"query": "concise answers", "layer": "relationship", "limit": 5}}',
            'tool_call: {"name": "record_memory", "arguments": {"layer": "relationship", "title": "Dustin prefers concise answers", "summary": "Dustin prefers concise, direct responses without preamble unless detail is requested.", "kind": "preference", "tags": ["preference", "tone"], "importance": 4}}',
            'tool_call: {"name": "move_memory", "arguments": {"memory_id": "abc-123", "new_layer": "semantic", "reason": "This was saved as episodic, but it is a durable factual concept."}}',
            'tool_call: {"name": "record_project_memory", "arguments": {"project_id": "stasis-c3804eb0", "category": "decision", "content": "We chose SQLite over JSON for the local cache."}}',
            'tool_call: {"name": "update_project_memory", "arguments": {"project_id": "stasis-c3804eb0", "section": "project_overview", "data": {"current_status": "Settings now includes a saved local-context timezone setup."}}}',
        ]

    content = "\n".join(
        [
            "You may use tools when they help. You may also answer directly.",
            "Do not claim tools are unavailable when this [Available Tools] section is present.",
            "",
            *format_lines,
            "",
            "Mode boundaries:",
            "- Chat: mode boundaries do not restrict tool use; normal runtime permission checks still apply.",
            "- Plan: strictly read-only. You may search/read/inspect only. Do not write, create, update, archive, move, merge, delete, install, test/build, or mutate files, memories, projects, or system state.",
            "- Debug: read freely. Write/create/update/archive/move/merge/delete only when directly related to diagnosing, reproducing, testing, or fixing a bug/error/failure.",
            "- The runtime enforces these boundaries. If a tool is blocked, answer with what you can do in the current mode or ask the user to switch modes.",
            *example_lines,
            "",
            "Memory Stewardship:",
            "- You have six canonical durable memory layers:",
            *layer_lines,
            "- Preference is not a top-level MemoryLayer. Store preferences as kind='preference', subtype metadata, or tags inside relationship, semantic, project, or procedural memories.",
            "- record_memory creates canonical memories in one of the six layers. It is the primary generic memory-write tool. Reject preference as a layer.",
            "- search_memory/list_memory are for inspecting existing memories before answering memory-specific questions, cleanup, updates, archiving, or reclassification.",
            "- update_memory corrects/refines an existing canonical memory. Prefer it over creating duplicates.",
            "- archive_memory retires a canonical memory. Prefer archive over hard delete.",
            "- move_memory reclassifies a memory when you notice the wrong layer; it preserves the memory id and writes audit history with previous/new layer, reason, timestamp, source, project_id, tags, and before/after data.",
            "- merge_memory merges duplicate/overlapping canonical memories into one target and archives the sources with audit history.",
            "- Legacy episodic compatibility tools are intentionally not model-facing. Use record_memory/search_memory/list_memory/update_memory/archive_memory/move_memory for all canonical memory layers.",
            "- record_project_memory is for quick append-only registered-project notes learned from conversation or tool results. It links to canonical project-layer metadata while keeping richer project memory intact.",
            "- update_project_memory maintains the richer Project Memory page sections: status/current_status, stack, purpose, safe-use notes, verified/inferred facts, architecture summary, important file info, symbol contracts, read-before-editing rules, decisions, tasks, and notes. Use it when the durable project memory should update a structured field instead of only appending a note.",
            "- For generated project fields, update_project_memory writes curated overrides layered over indexed memory so they survive project re-indexing.",
            "- Search memory before answering when the user asks what you remember, asks to clean memory up, asks to correct memory, or when remembered details are central to the answer.",
            "- Keep memory entries compact and distilled: save conclusions, not transcripts.",
            "- Do not save temporary, obvious, noisy, sensitive, or low-signal details unless the user clearly asks.",
            "- Do not write memory for one-off tool outputs, routine chatter, transient moods, secrets/credentials, or facts already represented unless the user explicitly asks or the durable value is clear.",
            "",
            "Tool use guidance:",
            "- Use glob_files for file discovery and search_text for content search before using run_shell_command for those tasks.",
            "- Use list_directory for directory inspection and read_file_range for large-file slices.",
            "- Use read_file for a known text file.",
            "- For generated artifacts or project files, prefer write_file, patch_file, and make_directory over shell heredocs. Relative paths default to ~/.bitbuddy/artifacts.",
            "- For artifact workflows such as KiCad, CAD, images, data files, scripts, or reports: generate deterministic source/scripts/files first, validate with command-line tools when available, then optionally use desktop MCP to inspect or open apps.",
            "- Use run_shell_command with working_directory for validators, exports, tests, and toolchain checks after files are written.",
            "- Use web_search for searching the web for information using SearxNG, then web_fetch to open and read the full text of a specific result or any direct URL.",
            "- Use run_subagent for bounded delegated research or implementation subtasks where a private worker can inspect context and report back.",
            "- Use list_skills to inspect available reusable procedures and load_skill before relying on a skill's detailed workflow.",
            "- Use create_skill, patch_skill, write_skill_file, archive_skill, and validate_skill only for explicit skill maintenance work under ~/.bitbuddy/skills/.",
            "- Use run_shell_command as terminal access for commands, searches, tests, debugging, validation, and approved changes.",
            "- Project ids come from the registered-project context when available.",
            "- After a tool result teaches something durable, consider saving it with the appropriate memory tool before answering. Skip memory writes for low-signal results.",
            "- After a tool result, answer normally unless another tool would genuinely help.",
            "- After read_file, normally confirm, summarize, explain, or answer from the file; do not paste the whole file by default.",
            "- Do not claim exact source behavior from project memory alone. Read source files before exact code claims or edits.",
            *desktop_lines,
            "- Do not list tools unless the user asks what tools are available.",
            "- When listing tools, use the exact tool names from [Available Tools] and stop there; do not add capabilities that are not listed.",
            "- The runtime handles validation, permissions, and mode limits.",
            "",
            "[Available Tools]",
            *tool_lines,
        ]
    )
    return {"role": "system", "content": content}


def _starts_with_xml_tool_call(stripped: str) -> bool:
    lowered = stripped.lower()
    return any(lowered.startswith(f"<{tag}") for tag in XML_TOOL_CALL_TAGS)


def contains_tool_call(text: str) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    return bool(re.search(rf"(?im)^\s*{re.escape(TOOL_CALL_PREFIX)}", text)) or _starts_with_xml_tool_call(stripped)


def contains_unsupported_tool_output(text: str) -> bool:
    return any(marker.lower() in text.lower() for marker in UNSUPPORTED_TOOL_MARKERS)


def _extract_tool_payload(text: str) -> str:
    stripped = text.strip()
    lowered = stripped.lower()

    if lowered.startswith(TOOL_CALL_PREFIX):
        return stripped[len(TOOL_CALL_PREFIX):].strip()

    for tag in XML_TOOL_CALL_TAGS:
        pattern = rf"^<\s*{tag}\s*>\s*(.*?)\s*</\s*{tag}\s*>$"
        match = re.match(pattern, stripped, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

    raise ToolParseError("Not a tool call.")


def _load_tool_payload(payload: str) -> dict[str, Any]:
    if len(payload) > MAX_TOOL_PAYLOAD_CHARS:
        raise ToolParseError("Tool call payload is too large.")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ToolParseError(f"Tool call payload is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ToolParseError("Tool call payload must be a JSON object.")

    return data


def _normalize_tool_call_data(data: dict[str, Any]) -> ToolCall:
    raw_tool_name = data.get("name") or data.get("tool") or data.get("type")
    if not isinstance(raw_tool_name, str) or not raw_tool_name.strip():
        raise ToolParseError(
            "Tool call payload requires a tool name. "
            "Use a JSON object like {\"name\": \"read_file\", \"arguments\": {...}}."
        )

    clean_tool = raw_tool_name.strip()

    reserved_keys = {"name", "tool", "type", "arguments"}
    top_level_arguments = {key: value for key, value in data.items() if key not in reserved_keys}

    raw_arguments = data.get("arguments")
    if raw_arguments is None:
        arguments = dict(top_level_arguments)
    elif isinstance(raw_arguments, dict):
        arguments = {**top_level_arguments, **raw_arguments}
    else:
        raise ToolParseError("Tool call payload requires an object 'arguments'.")

    arguments = normalize_tool_arguments(clean_tool, arguments)
    return ToolCall(tool=clean_tool, arguments=arguments)


def normalize_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize harmless model-facing aliases into the internal schema."""
    clean = dict(arguments)

    if tool_name == "read_file" and "file_path" not in clean:
        for alias in ("path", "filepath", "file"):
            value = clean.get(alias)
            if isinstance(value, str) and value.strip():
                clean["file_path"] = value
                break

    if tool_name == "run_shell_command" and "command" not in clean:
        for alias in ("cmd", "shell", "command_line"):
            value = clean.get(alias)
            if isinstance(value, str) and value.strip():
                clean["command"] = value
                break

    return clean


def parse_tool_call(text: str) -> ToolCall:
    """Parse tool calls from the preferred tool_call: prefix or compatibility XML."""
    payload = _extract_tool_payload(text)
    data = _load_tool_payload(payload)
    return _normalize_tool_call_data(data)


def parse_tool_calls(text: str) -> list[ToolCall]:
    """Parse one or more tool_call lines from a response.

    Multiple calls are allowed only when every non-blank line is a tool_call
    line. Prose mixed with tool calls is still malformed so it cannot leak into
    user-visible chat.
    """
    stripped = text.strip()
    if _starts_with_xml_tool_call(stripped):
        return [parse_tool_call(stripped)]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    tool_lines = [line for line in lines if line.lower().startswith(TOOL_CALL_PREFIX)]
    if not tool_lines:
        raise ToolParseError("Not a tool call.")
    if len(tool_lines) != len(lines):
        raise ToolParseError("Tool call responses must contain only tool_call lines and no prose.")

    calls: list[ToolCall] = []
    for line in tool_lines:
        payload = line[len(TOOL_CALL_PREFIX):].strip()
        data = _load_tool_payload(payload)
        calls.append(_normalize_tool_call_data(data))

    return calls


def parse_tool_call_lines(text: str) -> list[ToolCall]:
    """Parse valid tool_call lines while ignoring surrounding prose.

    This is intentionally separate from parse_tool_calls, which remains strict
    for normal protocol validation. The chat runtime uses this only as a repair
    path after a model already violated the protocol by mixing prose with calls.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    tool_lines = [line for line in lines if line.lower().startswith(TOOL_CALL_PREFIX)]
    if not tool_lines:
        raise ToolParseError("Not a tool call.")

    calls: list[ToolCall] = []
    for line in tool_lines:
        payload = line[len(TOOL_CALL_PREFIX):].strip()
        data = _load_tool_payload(payload)
        calls.append(_normalize_tool_call_data(data))

    return calls


def _strip_system_reminders(text: str) -> str:
    """Remove <system-reminder> blocks that may leak into model responses."""
    return re.sub(r"(?is)<system-reminder\b[^>]*>.*?(?:</system-reminder>|$)", "", text).strip()


def invalid_tool_result(error: str) -> ToolResult:
    return ToolResult(
        tool="invalid_tool_call",
        ok=False,
        content="",
        summary="Invalid tool call",
        arguments_summary={},
        error=f"Invalid tool call: {error}",
    )


def summarize_arguments(arguments: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
    query = arguments.get("query")
    if isinstance(query, str):
        summary["query"] = query[:160]
    category = arguments.get("category")
    if isinstance(category, str):
        summary["category"] = category[:40]
    episode_id = arguments.get("episode_id")
    if isinstance(episode_id, str):
        summary["episode_id"] = episode_id[:120]
    title_query = arguments.get("title_query")
    if isinstance(title_query, str):
        summary["title_query"] = title_query[:160]
    title = arguments.get("title")
    if isinstance(title, str):
        summary["title"] = title[:160]
    memory_id = arguments.get("memory_id")
    if isinstance(memory_id, str):
        summary["memory_id"] = memory_id[:120]
    layer = arguments.get("layer") or arguments.get("new_layer")
    if isinstance(layer, str):
        summary["layer"] = layer[:40]
    kind = arguments.get("kind")
    if isinstance(kind, str):
        summary["kind"] = kind[:80]
    project_id = arguments.get("project_id")
    if isinstance(project_id, str):
        summary["project_id"] = project_id[:120]
    file_path = arguments.get("file_path")
    if isinstance(file_path, str):
        summary["file_path"] = file_path[:240]
    command = arguments.get("command")
    if isinstance(command, str):
        summary["command"] = command[:400]
    return summary


def cap_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    omitted = len(text) - max_chars
    suffix = f"\n\n[truncated: omitted {omitted} characters due to tool result max_chars={max_chars}]"
    keep = max(0, max_chars - len(suffix))
    return f"{text[:keep].rstrip()}{suffix}", True


def needs_permission(call: ToolCall, definition: ToolDefinition | None = None) -> tuple[bool, str]:
    """
    Check if a tool call needs user permission.
    Returns (needs_permission, reason).
    """
    if is_mcp_mutating_tool(definition, call.tool):
        annotations = tool_annotations(definition)
        server = str(annotations.get("mcp_server") or "MCP server")
        original_tool = str(annotations.get("mcp_tool") or call.tool)
        if bool(annotations.get("openWorldHint")) or bool(annotations.get("destructiveHint")):
            return True, f"MCP tool `{original_tool}` from `{server}` can control external app or system state."
        return True, f"MCP tool `{original_tool}` from `{server}` can change local state."

    calendar_scope = CALENDAR_TOOL_SCOPES.get(call.tool)
    if calendar_scope:
        try:
            from ..calendar.permissions import permission_state
            from ..calendar.service import user_timezone
            from ..calendar.store import ensure_default_calendar

            account, _calendar = ensure_default_calendar(user_timezone())
            state = permission_state(account.id, calendar_scope)
        except Exception:
            state = "ask"
        if state == "ask":
            verb = {
                "read": "view your calendar",
                "create": "create calendar events",
                "modify": "modify calendar events",
                "delete": "delete calendar events",
            }.get(calendar_scope, f"use calendar scope `{calendar_scope}`")
            return True, f"Tool `{call.tool}` needs your permission to {verb}."

    email_scope = EMAIL_TOOL_SCOPES.get(call.tool)
    if email_scope:
        try:
            from ..email.permissions import permission_state
            from ..email.service import email_account_id

            state = permission_state(email_account_id(), email_scope)
        except Exception:
            state = "ask"
        if state == "ask":
            verb = {
                "read": "read your email",
                "search": "search your email",
                "watch": "watch your email for rules",
                "trash": "move email messages to Trash",
            }.get(email_scope, f"use email scope `{email_scope}`")
            return True, f"Tool `{call.tool}` needs your permission to {verb}."

    if call.tool in FILE_WRITE_TOOLS:
        if is_default_artifact_write(call):
            return False, ""
        summary = summarize_arguments(call.arguments)
        target = summary.get("path") or summary.get("file_path") or "target path"
        return True, f"Tool `{call.tool}` is attempting to write outside BitBuddy's managed artifacts workspace: `{target}`."

    # Scenario 1: Accessing a file outside of the user's home directory
    paths = extract_paths_from_arguments(call.arguments)
    for path_str in paths:
        if is_path_outside_home(path_str):
            return True, f"Tool `{call.tool}` is attempting to access a path outside your home directory: `{path_str}`."

    # Scenario 2: Edit/delete/create files (or other destructive actions)
    if call.tool == "run_shell_command":
        command = str(call.arguments.get("command", ""))
        if is_destructive_command(command):
            return True, f"The command `{command}` appears to be destructive (e.g., editing, deleting, or creating files)."

    return False, ""


def extract_paths_from_arguments(arguments: dict[str, object]) -> list[str]:
    paths = []
    for key in ("file_path", "path", "root_path", "working_directory"):
        path = arguments.get(key)
        if isinstance(path, str):
            paths.append(path)

    # For shell commands, we might want to look for absolute paths
    command = arguments.get("command")
    if isinstance(command, str):
        # Very naive absolute path extraction
        for part in command.split():
            if part.startswith("/"):
                paths.append(part)

    return paths


def is_default_artifact_write(call: ToolCall) -> bool:
    arguments = call.arguments
    if isinstance(arguments.get("project_id"), str) and str(arguments.get("project_id")).strip():
        return False

    file_path = arguments.get("file_path") or arguments.get("path")
    if isinstance(file_path, str) and file_path.strip():
        try:
            candidate = Path(file_path).expanduser()
            if candidate.is_absolute():
                return _is_under_managed_root(candidate)
        except Exception:
            return False

    root = arguments.get("root_path")
    if not isinstance(root, str) or not root.strip():
        return True

    try:
        root_path = Path(root).expanduser()
        if not root_path.is_absolute():
            root_path = (Path.cwd() / root_path).resolve()
        return _is_under_managed_root(root_path)
    except Exception:
        return False


def _is_under_managed_root(candidate: Path) -> bool:
    """True when an absolute path resolves inside a BitBuddy-managed write root."""
    resolved = candidate.resolve()
    for root in (ARTIFACTS_DIR, WORKSPACE_DIR):
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def is_path_outside_home(path_str: str) -> bool:
    try:
        path = Path(path_str).expanduser().resolve()
        home = Path.home().resolve()
        return not str(path).startswith(str(home))
    except Exception:
        # If we can't resolve it, be safe if it's an absolute path
        return path_str.startswith("/")


def is_destructive_command(command: str) -> bool:
    # A bit more comprehensive check for destructive patterns
    # We want to allow ls, grep, wc, cat, etc.
    safe_commands = {
        "ls", "grep", "wc", "cat", "head", "tail", "find", "du", "df",
        "ps", "top", "free", "uptime", "whoami", "pwd", "git status",
        "git log", "git diff", "git show", "git branch", "date", "echo"
    }

    # If the command starts with a safe command and doesn't have redirection
    parts = shlex.split(command)
    if not parts:
        return False

    main_cmd = Path(parts[0]).name
    if main_cmd in safe_commands and not any(op in command for op in (">", ">>", "|")):
        # Note: pipe '|' is allowed but could be complex, for now let's be conservative if it has pipes
        # Actually grep often uses pipes. Let's check for redirection specifically.
        if not any(op in command for op in (">", ">>")):
             return False

    # Patterns for destructive actions
    destructive_patterns = [
        r"\brm\b", r"\bmv\b", r"\bcp\b", r">", r">>", r"\btouch\b",
        r"\bmkdir\b", r"\bchmod\b", r"\bchown\b", r"\bsudo\b",
        r"\bdd\b", r"\bfdisk\b", r"\bmkfs\b", r"\bwipe\b",
        r"\bpython\b.*-m\s+pip\s+install", r"\bpip\s+install",
        r"\bnpm\s+install", r"\bpnpm\s+install", r"\byarn\s+add",
        r"\bapt-get\b", r"\byum\b", r"\bdnf\b", r"\bpacman\b"
    ]

    for pattern in destructive_patterns:
        if re.search(pattern, command):
            return True

    return False


def is_plan_safe_command(command: str) -> bool:
    """Return True only for commands that inspect state without mutating it."""
    clean = command.strip()
    if not clean:
        return True

    if re.search(r"(;|&&|\|\||`|\$\(|>|>>|<\(|\btee\b)", clean):
        return False

    mutation_patterns = [
        r"\brm\b", r"\brmdir\b", r"\bunlink\b", r"\bmv\b", r"\bcp\b",
        r"\btouch\b", r"\bmkdir\b", r"\bchmod\b", r"\bchown\b", r"\bsudo\b",
        r"\bdd\b", r"\bfdisk\b", r"\bmkfs\b", r"\bwipe\b", r"\btruncate\b",
        r"\binstall\b", r"\bpytest\b", r"\btox\b", r"\bmake\b", r"\bninja\b",
        r"\bnpm\b", r"\bpnpm\b", r"\byarn\b", r"\bpython\b", r"\bpython3\b",
    ]
    if any(re.search(pattern, clean, flags=re.IGNORECASE) for pattern in mutation_patterns):
        return False

    try:
        parts = shlex.split(clean)
    except ValueError:
        return False

    if not parts:
        return True

    main_cmd = Path(parts[0]).name

    if main_cmd == "git":
        read_only_git = {"status", "log", "diff", "show", "branch", "remote", "tag"}
        if len(parts) >= 2 and parts[1] in read_only_git and not any(part in {"-d", "-D", "--delete", "--set-upstream-to"} for part in parts):
            return True
        if len(parts) >= 2 and parts[1] == "config" and any(part in {"--get", "--get-all", "--list", "-l"} for part in parts[2:]):
            return True
        return False

    read_only_commands = {
        "ls", "grep", "rg", "wc", "cat", "head", "tail", "find", "du", "df",
        "ps", "top", "free", "uptime", "whoami", "pwd", "date", "echo", "stat",
        "file", "id", "env", "printenv", "which", "whereis", "command",
    }

    if main_cmd in read_only_commands:
        return True

    return False


def is_deletion_command(command: str) -> bool:
    """Return True if the command deletes files (blocked in Debug mode)."""
    deletion_patterns = [
        r"\brm\b", r"\brmdir\b", r"\bunlink\b", r"\bshred\b",
        r"\bwipe\b", r"\btrash\b", r"\bempty-trash\b",
    ]
    for pattern in deletion_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False
