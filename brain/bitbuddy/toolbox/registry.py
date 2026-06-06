from __future__ import annotations

from ..config import load_config
from ..mcp_client import McpError, get_mcp_client
from ..memory.layers import MEMORY_LAYER_VALUES
from .base import ToolDefinition, ToolRegistry
from .handlers import (
    archive_memory_tool,
    archive_skill_tool,
    calendar_create_event_tool,
    calendar_delete_event_tool,
    calendar_find_free_time_tool,
    calendar_modify_event_tool,
    calendar_view_events_tool,
    create_skill_tool,
    email_create_auto_trash_rule_tool,
    email_list_mailboxes_tool,
    email_read_message_tool,
    email_recent_messages_tool,
    email_search_messages_tool,
    email_trash_message_tool,
    glob_files_tool,
    get_project_brief_tool,
    get_project_memory_tool,
    list_skills_tool,
    list_directory_tool,
    list_memory_tool,
    merge_memory_tool,
    mcp_tool,
    move_memory_tool,
    read_file_tool,
    read_file_range_tool,
    record_memory_tool,
    record_project_memory_tool,
    run_shell_command_tool,
    run_subagent_tool,
    search_text_tool,
    search_memory_tool,
    load_skill_tool,
    patch_skill_tool,
    patch_file_tool,
    update_memory_tool,
    update_project_memory_tool,
    validate_skill_tool,
    web_fetch_tool,
    web_search_tool,
    make_directory_tool,
    write_file_tool,
    write_skill_file_tool,
)

def default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="glob_files",
            description="Find files by glob pattern under the current root or a registered project. Prefer this over shell for file discovery.",
            arguments_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "root_path": {"type": "string"}, "pattern": {"type": "string"}},
                "required": ["pattern"],
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        glob_files_tool,
    )
    registry.register(
        ToolDefinition(
            name="list_directory",
            description="List entries in a directory under the current root or a registered project. Prefer this over shell for directory inspection.",
            arguments_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "root_path": {"type": "string"}, "path": {"type": "string"}},
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        list_directory_tool,
    )
    registry.register(
        ToolDefinition(
            name="search_text",
            description="Search text files with a regular expression under the current root or a registered project. Prefer this over shell grep/rg.",
            arguments_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "root_path": {"type": "string"}, "pattern": {"type": "string"}, "include": {"type": "string"}},
                "required": ["pattern"],
                "additionalProperties": False,
            },
            max_chars=12000,
        ),
        search_text_tool,
    )
    registry.register(
        ToolDefinition(
            name="web_search",
            description="Search the web using SearxNG-compatible local search. Supports general text results and image results. Returns concise snippets and image URLs when category=images.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string", "enum": ["general", "images"]},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        web_search_tool,
    )
    registry.register(
        ToolDefinition(
            name="web_fetch",
            description="Fetch a single web page by URL and return its readable text content. Use after web_search to read a specific result, or when the user gives a direct URL to look at.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            max_chars=12000,
        ),
        web_fetch_tool,
    )
    registry.register(
        ToolDefinition(
            name="calendar_view_events",
            description="View calendar events. Use range=today|tomorrow|week|next_week|month for relative windows, or pass explicit ISO8601 start/end. Returns events with their ids.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "range": {"type": "string", "enum": ["today", "tomorrow", "week", "next_week", "month"]},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        calendar_view_events_tool,
    )
    registry.register(
        ToolDefinition(
            name="calendar_find_free_time",
            description="Find free time slots of a given duration within a range. Use before proposing a meeting time. Same range/start/end options as calendar_view_events.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "range": {"type": "string", "enum": ["today", "tomorrow", "week", "next_week", "month"]},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        calendar_find_free_time_tool,
    )
    registry.register(
        ToolDefinition(
            name="calendar_create_event",
            description="Create a calendar event. Requires the user's calendar 'create' permission. start/end are ISO8601 (e.g. 2026-06-05T14:30). Returns the new event id and any overlap warnings.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "start", "end"],
                "additionalProperties": False,
            },
            max_chars=2000,
        ),
        calendar_create_event_tool,
    )
    registry.register(
        ToolDefinition(
            name="calendar_modify_event",
            description="Modify an existing calendar event by id. Requires the user's calendar 'modify' permission. Only pass the fields you want to change.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "status": {"type": "string", "enum": ["confirmed", "tentative", "cancelled"]},
                },
                "required": ["event_id"],
                "additionalProperties": False,
            },
            max_chars=2000,
        ),
        calendar_modify_event_tool,
    )
    registry.register(
        ToolDefinition(
            name="calendar_delete_event",
            description="Delete a calendar event by id. Requires the user's calendar 'delete' permission.",
            arguments_schema={
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
                "additionalProperties": False,
            },
            max_chars=1000,
        ),
        calendar_delete_event_tool,
    )
    registry.register(
        ToolDefinition(
            name="email_list_mailboxes",
            description="List configured email mailboxes/folders. Read-only and requires email read permission.",
            arguments_schema={"type": "object", "properties": {}, "additionalProperties": False},
            max_chars=4000,
        ),
        email_list_mailboxes_tool,
    )
    registry.register(
        ToolDefinition(
            name="email_recent_messages",
            description="List recent email messages from a mailbox. Use whenever the user asks about inbox/email/messages or asks you to scan mail. Read-only; returns message ids for email_read_message.",
            arguments_schema={
                "type": "object",
                "properties": {"mailbox": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        email_recent_messages_tool,
    )
    registry.register(
        ToolDefinition(
            name="email_search_messages",
            description="Search email subjects/senders/snippets in a mailbox. Use for email awareness, finding useful messages, receipts, appointments, travel, bills, or calendar-worthy emails. Read-only.",
            arguments_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "mailbox": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                "required": ["query"],
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        email_search_messages_tool,
    )
    registry.register(
        ToolDefinition(
            name="email_read_message",
            description="Read one email message by id and mailbox. Read-only; does not mark read, reply, delete, or archive.",
            arguments_schema={
                "type": "object",
                "properties": {"message_id": {"type": "string"}, "mailbox": {"type": "string"}},
                "required": ["message_id"],
                "additionalProperties": False,
            },
            max_chars=16000,
        ),
        email_read_message_tool,
    )
    registry.register(
        ToolDefinition(
            name="email_trash_message",
            description="Move one email message to Trash. Recoverable, not permanent delete. Requires email trash permission and Gmail modify access.",
            arguments_schema={
                "type": "object",
                "properties": {"message_id": {"type": "string"}, "mailbox": {"type": "string"}},
                "required": ["message_id"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        email_trash_message_tool,
    )
    registry.register(
        ToolDefinition(
            name="email_create_auto_trash_rule",
            description="Create a sender rule that automatically moves future matching emails to Trash, optionally applying it to existing matching messages. Requires explicit email trash permission.",
            arguments_schema={
                "type": "object",
                "properties": {"sender": {"type": "string"}, "apply_existing": {"type": "boolean"}, "mailbox": {"type": "string"}},
                "required": ["sender"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        email_create_auto_trash_rule_tool,
    )
    registry.register(
        ToolDefinition(
            name="get_project_memory",
            description="Load structured memory for one registered project. Use for architecture, implementation notes, source areas, or deeper project details.",
            arguments_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
                "additionalProperties": False,
            },
            max_chars=24000,
        ),
        get_project_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="get_project_brief",
            description="Load a compact briefing for one registered project. Use for a quick project overview once the project_id is known.",
            arguments_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
                "additionalProperties": False,
            },
            max_chars=16000,
        ),
        get_project_brief_tool,
    )
    registry.register(
        ToolDefinition(
            name="record_memory",
            description="Create a compact durable memory in one canonical layer. This is the primary memory-write tool for episodic, semantic, project-linked, procedural, self, and relationship memory. Preference is a kind/tag, not a layer.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "enum": list(MEMORY_LAYER_VALUES)},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "kind": {"type": "string"},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "project_id": {"type": "string"},
                    "source": {"type": "string"},
                    "explicit_user_request": {"type": "boolean"},
                },
                "required": ["layer", "title", "summary"],
                "additionalProperties": False,
            },
            max_chars=3000,
        ),
        record_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="search_memory",
            description="Search canonical memories across layers or within one layer. Use before answering memory-specific questions, updating, archiving, or reclassifying memories.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "layer": {"type": "string", "enum": list(MEMORY_LAYER_VALUES)},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "include_archived": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        search_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="list_memory",
            description="List recent canonical memories, optionally by layer and project_id. Use for layer views, audits, and cleanup before deciding what to change.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "enum": list(MEMORY_LAYER_VALUES)},
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "include_archived": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        list_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read a specific text file safely. Use this for known file paths. With project_id, file_path is project-relative; without it, file_path may be absolute or home-relative.",
            arguments_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "file_path": {"type": "string"}},
                "required": ["file_path"],
                "additionalProperties": False,
            },
            max_chars=24000,
        ),
        read_file_tool,
    )
    registry.register(
        ToolDefinition(
            name="read_file_range",
            description="Read a line range from a text file. Use for large files when only part of the file is needed.",
            arguments_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "root_path": {"type": "string"}, "file_path": {"type": "string"}, "start_line": {"type": "integer"}, "line_count": {"type": "integer"}},
                "required": ["file_path"],
                "additionalProperties": False,
            },
            max_chars=24000,
        ),
        read_file_range_tool,
    )
    registry.register(
        ToolDefinition(
            name="run_shell_command",
            description="Terminal access. Run a shell command and return stdout/stderr. Use for environment inspection, searches, tests, debugging, validation, and approved file changes. Prefer write_file/patch_file for file authoring and read_file for reading a known text file.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "working_directory": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        run_shell_command_tool,
    )
    registry.register(
        ToolDefinition(
            name="write_file",
            description="Create or replace a text file. Relative paths default to ~/.bitbuddy/artifacts; use root_path or project_id for approved writes elsewhere. Prefer this over shell heredocs for generated artifacts.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "root_path": {"type": "string"},
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                    "create_dirs": {"type": "boolean"},
                },
                "required": ["file_path", "content"],
                "additionalProperties": False,
            },
            max_chars=12000,
        ),
        write_file_tool,
    )
    registry.register(
        ToolDefinition(
            name="patch_file",
            description="Patch a text file by replacing old_text with new_text. Relative paths default to ~/.bitbuddy/artifacts; use root_path or project_id for approved project edits.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "root_path": {"type": "string"},
                    "file_path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["file_path", "old_text", "new_text"],
                "additionalProperties": False,
            },
            max_chars=12000,
        ),
        patch_file_tool,
    )
    registry.register(
        ToolDefinition(
            name="make_directory",
            description="Create a directory. Relative paths default to ~/.bitbuddy/artifacts; use root_path or project_id for approved directories elsewhere.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "root_path": {"type": "string"},
                    "path": {"type": "string"},
                    "parents": {"type": "boolean"},
                    "exist_ok": {"type": "boolean"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        make_directory_tool,
    )
    registry.register(
        ToolDefinition(
            name="run_subagent",
            description="Delegate a bounded research or implementation subtask to a private subagent. The subagent can use allowed tools and returns a concise report to you.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "agent_type": {"type": "string"},
                    "project_id": {"type": "string"},
                    "allowed_tools": {"type": "array", "items": {"type": "string"}},
                    "max_rounds": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            max_chars=16000,
        ),
        run_subagent_tool,
    )
    registry.register(
        ToolDefinition(
            name="list_skills",
            description="List BitBuddy skills stored under ~/.bitbuddy/skills. Use before creating or selecting reusable procedures.",
            arguments_schema={
                "type": "object",
                "properties": {"include_archived": {"type": "boolean"}},
                "additionalProperties": False,
            },
            max_chars=12000,
        ),
        list_skills_tool,
    )
    registry.register(
        ToolDefinition(
            name="load_skill",
            description="Load the full SKILL.md for one BitBuddy skill. Use before following or editing that skill's detailed workflow.",
            arguments_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            max_chars=24000,
        ),
        load_skill_tool,
    )
    registry.register(
        ToolDefinition(
            name="validate_skill",
            description="Validate a BitBuddy skill's SKILL.md frontmatter, name, body, and support-file layout.",
            arguments_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        validate_skill_tool,
    )
    registry.register(
        ToolDefinition(
            name="create_skill",
            description="Create a new BitBuddy skill under ~/.bitbuddy/skills/<name>/SKILL.md. Use only for explicit skill maintenance requests.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "body": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["name", "description", "body"],
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        create_skill_tool,
    )
    registry.register(
        ToolDefinition(
            name="patch_skill",
            description="Patch one existing BitBuddy skill by replacing old_text with new_text in SKILL.md. Use for small skill edits.",
            arguments_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
                "required": ["name", "old_text", "new_text"],
                "additionalProperties": False,
            },
            max_chars=8000,
        ),
        patch_skill_tool,
    )
    registry.register(
        ToolDefinition(
            name="archive_skill",
            description="Archive a BitBuddy skill so it no longer appears in normal skill discovery. Prefer archive over deletion.",
            arguments_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        archive_skill_tool,
    )
    registry.register(
        ToolDefinition(
            name="write_skill_file",
            description="Write a supporting file inside an existing skill under references/, templates/, scripts/, or assets/. Does not edit SKILL.md.",
            arguments_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "relative_path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["name", "relative_path", "content"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        write_skill_file_tool,
    )
    registry.register(
        ToolDefinition(
            name="record_project_memory",
            description="Add a durable note to a registered project when a tool result or conversation reveals a project-specific decision, fact, architecture note, or task. Do not save temporary or obvious details.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "category": {"type": "string", "enum": ["decision", "fact", "task", "architecture"]},
                    "content": {"type": "string"},
                },
                "required": ["project_id", "category", "content"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        record_project_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="update_project_memory",
            description="Update structured project memory fields that appear on the Project Memory page. Use for maintained status, stack, purpose, safe-use notes, verified/inferred facts, architecture summaries, important file info, symbol contracts, read-before-editing rules, decisions, tasks, or notes. Curated updates are layered over indexed memory so they survive re-indexing.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "section": {
                        "type": "string",
                        "enum": [
                            "project_overview",
                            "architecture_summary",
                            "read_rule",
                            "file_info",
                            "symbol_contract",
                            "decision",
                            "task",
                            "note",
                        ],
                    },
                    "data": {"type": "object"},
                },
                "required": ["project_id", "section", "data"],
                "additionalProperties": False,
            },
            max_chars=5000,
        ),
        update_project_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="update_memory",
            description="Update an existing canonical memory by memory_id. Prefer updating over creating duplicates when refining or correcting memory.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "kind": {"type": "string"},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "project_id": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
            max_chars=3000,
        ),
        update_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="archive_memory",
            description="Archive a canonical memory by memory_id. Prefer archive over hard delete. Use when the user asks to remove/forget/clean up a memory or when retiring an obsolete duplicate.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "explicit_user_request": {"type": "boolean"},
                },
                "required": ["memory_id", "reason"],
                "additionalProperties": False,
            },
            max_chars=2000,
        ),
        archive_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="move_memory",
            description="Reclassify a canonical memory into a different layer while preserving memory_id and writing audit history. Use when a memory was saved into the wrong layer.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "new_layer": {"type": "string", "enum": list(MEMORY_LAYER_VALUES)},
                    "reason": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["memory_id", "new_layer", "reason"],
                "additionalProperties": False,
            },
            max_chars=3000,
        ),
        move_memory_tool,
    )
    registry.register(
        ToolDefinition(
            name="merge_memory",
            description="Merge duplicate or overlapping canonical memories into one target memory, then archive the source memories. Prefer this over hard deletion when consolidating duplicates.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "target_memory_id": {"type": "string"},
                    "source_memory_ids": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "kind": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["target_memory_id", "source_memory_ids", "reason"],
                "additionalProperties": False,
            },
            max_chars=4000,
        ),
        merge_memory_tool,
    )
    register_mcp_tools(registry)
    return registry


def register_mcp_tools(registry: ToolRegistry) -> None:
    config = load_config()
    if not config.mcp.enabled:
        return
    for server in config.mcp_servers:
        if not server.enabled:
            continue
        try:
            tools = get_mcp_client(server).tools()
        except McpError:
            continue
        for tool in tools:
            registered_name = f"mcp_{server.name}_{normalize_mcp_tool_name(tool.name)}"
            annotations = dict(tool.annotations)
            annotations.update(
                {
                    "mcp": True,
                    "mcp_server": server.name,
                    "mcp_tool": tool.name,
                }
            )
            registry.register(
                ToolDefinition(
                    name=registered_name,
                    description=mcp_description(server.name, tool.name, tool.description, annotations),
                    arguments_schema=tool.input_schema or {"type": "object", "properties": {}, "additionalProperties": True},
                    max_chars=24000,
                    annotations=annotations,
                ),
                mcp_tool,
            )


def normalize_mcp_tool_name(name: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or "").strip())
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean.strip("_") or "tool"


def mcp_description(server_name: str, tool_name: str, description: str, annotations: dict[str, object]) -> str:
    safety = "read-only" if annotations.get("readOnlyHint") else "requires permission before use"
    if annotations.get("openWorldHint") or annotations.get("destructiveHint"):
        safety = "can control external app/system state; requires permission before use"
    return f"MCP tool `{tool_name}` from `{server_name}` ({safety}). {description}"
