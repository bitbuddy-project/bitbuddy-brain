from __future__ import annotations

import json
import queue
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .chats.repository import (
    chat_summary_to_json,
    create_chat,
    delete_chat,
    delete_chat_message_turn,
    get_chat,
    list_recent_chats,
    replace_chat_messages,
    trim_chat_from_message,
)
from .chats.greeting import return_greeting_text
from .chats.runtime import start_chat_run
from .memory.episodic import (
    Episode,
    create_episode,
    list_recent_episodes,
    search_episodes,
)
from .memory.layers import layer_catalog, memory_layer
from .memory.store import archive_memory, create_memory as create_generic_memory, get_memory, memory_to_json, move_memory, search_memories, update_memory as update_generic_memory
from .chats.state import (
    ActiveChatRun,
    ClientDisconnected,
    active_chat_run,
    register_chat_run,
)
from .config import BitBuddyConfig, load_config, load_personality, update_autonomy_config, update_chat_config, update_dreaming_config, update_mcp_config, update_model_runtime_config, update_user_context, upsert_mcp_server
from .continuity import record_continuity_event
from .personality import load_selected_personality, selected_personality_to_legacy_dict
from .paths import APP_DIR, CONFIG_PATH, PERSONALITIES_DIR, PERSONALITY_PATH
from .skills import archive_skill, create_skill, list_skills, load_skill, patch_skill, skill_to_json, validate_skill
from .workspace import archive_workspace_document, list_workspace_documents, read_workspace_document, set_workspace_document_pinned, workspace_document_to_json
from .memory.project import (
    index_project,
    list_projects,
    project_map,
    project_model,
    register_project,
    unregister_project,
)
from .notifications import dismiss_notification, list_notifications, mark_all_notifications_read, mark_notification_read, notification_to_json, unread_notification_count
from .self_model import add_self_journal, create_goal, get_self_state, list_goals, record_conversation_signal, update_goal, update_self_state
from .prompt_builder import build_chat_messages, chat_context_usage, latest_user_message, title_from_text
from .providers import ProviderClient
from .utils import autonomy_activity, log_activity, permission_activity, project_to_json
from .autonomy.delivery_scheduler import clear_background_delivery_notifications, set_active_visible_chat, unread_background_deliveries
from .autonomy.intentions import dismiss_intention, intention_to_json, list_pending_intentions
from .autonomy.runner import autonomy_status
from .autonomy.timeline import autonomy_timeline
from .dreaming.runtime import list_dream_runs, list_dream_tasks
from .lifecycle import get_lifecycle_state, lifecycle_status, record_user_activity
from .managed_tools import computer_use_linux_status, install_computer_use_linux, resolve_managed_command


STREAM_HEARTBEAT_SECONDS = 15


class BitBuddyRequestHandler(BaseHTTPRequestHandler):
    server_version = "BitBuddy/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        try:
            if path == "/health":
                self.send_json({"ok": True, "name": "bitbuddy", "home": str(APP_DIR)})
                return

            if path == "/config":
                self.send_json(config_to_json(load_config()))
                return

            if path == "/mcp/status":
                self.send_json(mcp_status_to_json())
                return

            if path == "/personality":
                config = load_config()
                selected_personality = load_selected_personality(config.personality)
                legacy = load_personality()
                selected = selected_personality_to_legacy_dict(config.name, selected_personality)
                selected["legacy"] = legacy
                self.send_json(selected)
                return

            if path == "/provider/health":
                ok, message = ProviderClient(load_config().provider).health()
                self.send_json(
                    {"ok": ok, "message": message},
                    status=HTTPStatus.OK if ok else HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

            if path == "/provider/models":
                self.send_json({"models": ProviderClient(load_config().provider).models()})
                return

            if path == "/provider/context":
                self.send_json(ProviderClient(load_config().provider).context_window())
                return

            if path == "/projects":
                self.send_json({"projects": [project_to_json(project) for project in list_projects()]})
                return

            if path == "/skills":
                params = parse_qs(urlparse(self.path).query)
                include_archived = params.get("include_archived", ["false"])[0].lower() == "true"
                self.send_json({"skills": [skill_to_json(skill) for skill in list_skills(include_archived=include_archived)]})
                return

            if path.startswith("/skills/"):
                skill_name = unquote(path.removeprefix("/skills/").strip("/"))
                if skill_name and "/" not in skill_name:
                    self.send_json(skill_to_json(load_skill(skill_name, mark_viewed=True), include_content=True))
                    return

            if path == "/workspace":
                params = parse_qs(urlparse(self.path).query)
                kind = params.get("kind", [""])[0]
                status = params.get("status", ["active"])[0] or "active"
                documents = list_workspace_documents(kind=kind, status=status, limit=200)
                self.send_json({"documents": [workspace_document_to_json(doc) for doc in documents]})
                return

            if path.startswith("/workspace/"):
                doc_id = unquote(path.removeprefix("/workspace/").strip("/"))
                if doc_id and "/" not in doc_id:
                    document = read_workspace_document(doc_id)
                    if document is None:
                        self.send_json({"error": "Document not found."}, status=HTTPStatus.NOT_FOUND)
                        return
                    self.send_json(workspace_document_to_json(document, include_body=True))
                    return

            if path == "/activity":
                self.send_json({"activity": autonomy_activity()})
                return

            if path == "/autonomy/status":
                self.send_json({"autonomy": autonomy_status()})
                return

            if path == "/autonomy/timeline":
                self.send_json({"timeline": autonomy_timeline()})
                return

            if path == "/lifecycle/status":
                self.send_json({"lifecycle": lifecycle_status()})
                return

            if path == "/dreams":
                self.send_json({"dreams": list_dream_runs(limit=50)})
                return

            if path.startswith("/dreams/"):
                dream_id = unquote(path.removeprefix("/dreams/").strip("/"))
                if dream_id and "/" not in dream_id:
                    self.send_json({"dream_id": dream_id, "tasks": list_dream_tasks(dream_id)})
                    return

            if path == "/autonomy/intentions":
                self.send_json({"intentions": [intention_to_json(item) for item in list_pending_intentions(limit=50)]})
                return

            if path == "/self":
                self.send_json(get_self_state())
                return

            if path == "/goals":
                params = parse_qs(urlparse(self.path).query)
                include_done = params.get("include_done", ["false"])[0].lower() == "true"
                self.send_json({"goals": [goal.__dict__ for goal in list_goals(include_done=include_done)]})
                return

            if path == "/permissions/activity":
                self.send_json({"activity": permission_activity()})
                return

            if path == "/memory/episodes":
                self.send_json({"episodes": [_episode_to_json(ep) for ep in list_recent_episodes()]})
                return

            if path == "/memory/episodes/search":
                params = parse_qs(urlparse(self.path).query)
                q = params.get("q", [""])[0]
                self.send_json({"episodes": [_episode_to_json(ep) for ep in search_episodes(q)]})
                return

            if path == "/memory/layers":
                self.send_json({"layers": layer_catalog(), "preference_layer": False})
                return

            if path == "/memory":
                params = parse_qs(urlparse(self.path).query)
                layer = params.get("layer", [""])[0] or None
                query_text = params.get("q", [""])[0]
                project_id = params.get("project_id", [""])[0] or None
                include_archived = params.get("include_archived", ["false"])[0].lower() == "true"
                try:
                    limit = int(params.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                memories = search_memories(
                    query=query_text,
                    layer=layer,
                    project_id=project_id,
                    limit=limit,
                    include_archived=include_archived,
                )
                self.send_json({"memories": [memory_to_json(memory) for memory in memories]})
                return

            if path.startswith("/memory/"):
                memory_id = unquote(path.removeprefix("/memory/").strip("/"))
                if memory_id and "/" not in memory_id:
                    self.send_json(memory_to_json(get_memory(memory_id, include_archived=True)))
                    return

            if path == "/chat/active/notifications":
                self.send_json({"notifications": unread_background_deliveries()})
                return

            if path == "/notifications":
                params = parse_qs(urlparse(self.path).query)
                try:
                    after_id = int(params.get("after_id", ["0"])[0])
                except ValueError:
                    after_id = 0
                try:
                    limit = int(params.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                include_dismissed = params.get("include_dismissed", ["false"])[0].lower() == "true"
                notifications = list_notifications(after_id=after_id, limit=limit, include_dismissed=include_dismissed)
                self.send_json(
                    {
                        "notifications": [notification_to_json(notification) for notification in notifications],
                        "unread_count": unread_notification_count(),
                    }
                )
                return

            if path == "/chats":
                params = parse_qs(urlparse(self.path).query)
                try:
                    limit = min(500, int(params.get("limit", ["20"])[0]))
                except ValueError:
                    limit = 20
                search = params.get("search", [""])[0]
                self.send_json({"chats": [chat_summary_to_json(chat) for chat in list_recent_chats(limit=limit, search=search)]})
                return

            if path.startswith("/chats/"):
                chat_id = unquote(path.removeprefix("/chats/").strip("/"))

                try:
                    self.send_json(get_chat(chat_id))
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.NOT_FOUND)

                return

            if path.startswith("/projects/") and path.endswith("/map"):
                project_id = unquote(path.removeprefix("/projects/").removesuffix("/map").strip("/"))
                self.send_json({"project": project_id, "map": project_map(project_id)})
                return

            if path.startswith("/projects/") and path.endswith("/memory"):
                project_id = unquote(path.removeprefix("/projects/").removesuffix("/memory").strip("/"))
                self.send_json({"project": project_id, "memory": project_model(project_id)})
                return

            if path == "/subagents/runs":
                params = parse_qs(urlparse(self.path).query)
                try:
                    limit = min(50, int(params.get("limit", ["20"])[0]))
                except ValueError:
                    limit = 20
                self.send_json({"runs": list_subagent_runs(limit=limit)})
                return

            self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except ClientDisconnected:
            return
        except Exception as error:
            self.send_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        try:
            if path == "/projects":
                body = self.read_json()
                name = body.get("name") if isinstance(body.get("name"), str) else ""
                paths = body.get("paths")

                if not name.strip():
                    self.send_json({"error": "Project name is required."}, status=HTTPStatus.BAD_REQUEST)
                    return

                if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
                    self.send_json({"error": "Project paths must be a list of strings."}, status=HTTPStatus.BAD_REQUEST)
                    return

                clean_paths = [path.strip() for path in paths if path.strip()]

                if not clean_paths:
                    self.send_json({"error": "At least one project path is required."}, status=HTTPStatus.BAD_REQUEST)
                    return

                try:
                    project = register_project(name.strip(), clean_paths)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return

                self.send_json({"project": project_to_json(project)}, status=HTTPStatus.CREATED)
                return

            if path == "/skills":
                body = self.read_json()
                try:
                    skill = create_skill(
                        str(body.get("name") or ""),
                        str(body.get("description") or ""),
                        str(body.get("body") or ""),
                        version=str(body.get("version") or "1.0.0"),
                        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                    )
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(skill_to_json(skill, include_content=True), status=HTTPStatus.CREATED)
                return

            if path == "/skills/reload":
                self.send_json({"skills": [skill_to_json(skill) for skill in list_skills(include_archived=True)]})
                return

            if path.startswith("/skills/") and path.endswith("/archive"):
                skill_name = unquote(path.removeprefix("/skills/").removesuffix("/archive").strip("/"))
                try:
                    self.send_json(skill_to_json(archive_skill(skill_name)))
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                return

            if path.startswith("/workspace/") and path.endswith("/archive"):
                doc_id = unquote(path.removeprefix("/workspace/").removesuffix("/archive").strip("/"))
                ok = archive_workspace_document(doc_id)
                self.send_json({"ok": ok}, status=HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND)
                return

            if path.startswith("/workspace/") and path.endswith("/pin"):
                doc_id = unquote(path.removeprefix("/workspace/").removesuffix("/pin").strip("/"))
                body = self.read_json_body()
                set_workspace_document_pinned(doc_id, bool(body.get("pinned", True)))
                self.send_json({"ok": True})
                return

            if path.startswith("/skills/") and path.endswith("/validate"):
                skill_name = unquote(path.removeprefix("/skills/").removesuffix("/validate").strip("/"))
                validation = validate_skill(skill_name)
                self.send_json(
                    {"ok": validation.ok, "errors": list(validation.errors), "warnings": list(validation.warnings)},
                    status=HTTPStatus.OK if validation.ok else HTTPStatus.BAD_REQUEST,
                )
                return

            if path.startswith("/autonomy/intentions/") and path.endswith("/dismiss"):
                raw_id = unquote(path.removeprefix("/autonomy/intentions/").removesuffix("/dismiss").strip("/"))
                try:
                    intention_id = int(raw_id)
                except ValueError:
                    self.send_json({"error": "Invalid intention id."}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"dismissed": dismiss_intention(intention_id)})
                return

            if path == "/self/journal":
                body = self.read_json()
                try:
                    entry = add_self_journal(
                        str(body.get("kind") or "reflection"),
                        str(body.get("title") or ""),
                        str(body.get("body") or ""),
                        body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                    )
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(entry.__dict__, status=HTTPStatus.CREATED)
                return

            if path == "/goals":
                body = self.read_json()
                try:
                    goal = create_goal(
                        str(body.get("title") or ""),
                        why=str(body.get("why") or ""),
                        owner=str(body.get("owner") or "self"),
                        horizon=str(body.get("horizon") or "ongoing"),
                        risk_level=int(body.get("risk_level", 1)),
                        autonomy_allowed=bool(body.get("autonomy_allowed", True)),
                        next_action=str(body.get("next_action") or ""),
                        evidence=str(body.get("evidence") or ""),
                        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                    )
                except (ValueError, TypeError) as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(goal.__dict__, status=HTTPStatus.CREATED)
                return

            if path.startswith("/projects/") and path.endswith("/index"):
                project_id = unquote(path.removeprefix("/projects/").removesuffix("/index").strip("/"))
                result = index_project(project_id)

                self.send_json(
                    {
                        "project": project_to_json(result.project),
                        "scanned": result.scanned,
                        "changed": result.changed,
                        "deleted": result.deleted,
                        "skipped": result.skipped,
                        "roots": result.roots,
                        "changed_paths": result.changed_paths,
                        "deleted_paths": result.deleted_paths,
                        "skipped_paths": result.skipped_paths,
                    }
                )
                return

            if path == "/chat/context":
                self.send_json(chat_context_usage(self.read_json()))
                return

            if path == "/chat/cancel":
                self.cancel_chat(self.read_json())
                return

            if path == "/chat/permission":
                self.permission(self.read_json())
                return

            if path == "/chat/active":
                body = self.read_json()
                chat_id = body.get("chat_id") if isinstance(body.get("chat_id"), str) else ""
                set_active_visible_chat(chat_id)
                if chat_id:
                    clear_background_delivery_notifications(chat_id)
                self.send_json({"ok": True, "active_chat_id": chat_id})
                return

            if path == "/mcp/computer-use-linux/install":
                status = install_computer_use_linux()
                self.send_json(mcp_status_to_json(message=status.message), status=HTTPStatus.OK if status.available else HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            if path == "/mcp/computer-use-linux/configure":
                update_mcp_config({"enabled": True})
                upsert_mcp_server("computer-use-linux", "managed:computer-use-linux", ["mcp"], timeout=120, connect_timeout=30, enabled=True)
                self.send_json(mcp_status_to_json(message="Configured Linux desktop-control MCP server."))
                return

            if path == "/mcp/computer-use-linux/doctor":
                status = computer_use_linux_status()
                if not status.available:
                    self.send_json(mcp_status_to_json(message=status.message), status=HTTPStatus.BAD_REQUEST)
                    return
                command = resolve_managed_command("managed:computer-use-linux")
                result = subprocess.run([command, "doctor"], capture_output=True, text=True, timeout=60)
                self.send_json(
                    mcp_status_to_json(
                        message="Desktop-control doctor completed." if result.returncode == 0 else "Desktop-control doctor reported issues.",
                        doctor={"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode},
                    ),
                    status=HTTPStatus.OK if result.returncode == 0 else HTTPStatus.BAD_REQUEST,
                )
                return

            if path == "/notifications/read-all":
                self.send_json({"updated": mark_all_notifications_read(), "unread_count": unread_notification_count()})
                return

            if path.startswith("/notifications/") and path.endswith("/read"):
                notification_id = parse_notification_id(path, suffix="read")
                if notification_id <= 0:
                    self.send_json({"error": "Invalid notification id."}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"read": mark_notification_read(notification_id), "unread_count": unread_notification_count()})
                return

            if path.startswith("/notifications/") and path.endswith("/dismiss"):
                notification_id = parse_notification_id(path, suffix="dismiss")
                if notification_id <= 0:
                    self.send_json({"error": "Invalid notification id."}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"dismissed": dismiss_notification(notification_id), "unread_count": unread_notification_count()})
                return

            if path.startswith("/chats/") and path.endswith("/trim-from-message"):
                chat_id, message_id = parse_chat_message_path(path, suffix="trim-from-message")
                if not chat_id or message_id <= 0:
                    self.send_json({"error": "Invalid chat message path."}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    self.send_json(trim_chat_from_message(chat_id, message_id))
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                return

            if path == "/chat/stream":
                self.stream_chat(self.read_json())
                return

            if path == "/memory/episodes":
                body = self.read_json()
                title = body.get("title") if isinstance(body.get("title"), str) else ""
                summary = body.get("summary") if isinstance(body.get("summary"), str) else ""
                if not title.strip() or not summary.strip():
                    self.send_json({"error": "title and summary are required."}, status=HTTPStatus.BAD_REQUEST)
                    return
                episode = create_episode(
                    title=title,
                    summary=summary,
                    type=body.get("type") if isinstance(body.get("type"), str) else "episode",
                    importance=int(body.get("importance", 3)),
                    conversation_id=body.get("conversation_id") if isinstance(body.get("conversation_id"), str) else None,
                    project_id=body.get("project_id") if isinstance(body.get("project_id"), str) else None,
                    emotional_tone=body.get("emotional_tone") if isinstance(body.get("emotional_tone"), str) else None,
                    source=body.get("source") if isinstance(body.get("source"), str) else None,
                    tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
                    metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                )
                self.send_json(_episode_to_json(episode), status=HTTPStatus.CREATED)
                return

            if path == "/memory":
                body = self.read_json()
                title = body.get("title") if isinstance(body.get("title"), str) else ""
                summary = body.get("summary") if isinstance(body.get("summary"), str) else ""
                layer = body.get("layer") if isinstance(body.get("layer"), str) else ""
                if not title.strip() or not summary.strip() or not layer.strip():
                    self.send_json({"error": "layer, title and summary are required."}, status=HTTPStatus.BAD_REQUEST)
                    return
                memory = create_generic_memory(
                    layer=memory_layer(layer),
                    kind=body.get("kind") if isinstance(body.get("kind"), str) else "memory",
                    title=title,
                    summary=summary,
                    importance=int(body.get("importance", 3)),
                    conversation_id=body.get("conversation_id") if isinstance(body.get("conversation_id"), str) else None,
                    project_id=body.get("project_id") if isinstance(body.get("project_id"), str) else None,
                    emotional_tone=body.get("emotional_tone") if isinstance(body.get("emotional_tone"), str) else None,
                    source=body.get("source") if isinstance(body.get("source"), str) else "http_api",
                    tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
                    metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                )
                self.send_json(memory_to_json(memory), status=HTTPStatus.CREATED)
                return

            if path.startswith("/memory/") and path.endswith("/archive"):
                memory_id = unquote(path.removeprefix("/memory/").removesuffix("/archive").strip("/"))
                body = self.read_json()
                reason = body.get("reason") if isinstance(body.get("reason"), str) else "Archived via API."
                self.send_json(memory_to_json(archive_memory(memory_id, reason=reason, source="http_api")))
                return

            if path.startswith("/memory/") and path.endswith("/move"):
                memory_id = unquote(path.removeprefix("/memory/").removesuffix("/move").strip("/"))
                body = self.read_json()
                new_layer = body.get("new_layer") if isinstance(body.get("new_layer"), str) else ""
                reason = body.get("reason") if isinstance(body.get("reason"), str) else ""
                self.send_json(
                    memory_to_json(
                        move_memory(
                            memory_id,
                            new_layer=new_layer,
                            reason=reason,
                            source="http_api",
                            source_metadata=body.get("source_metadata") if isinstance(body.get("source_metadata"), dict) else {},
                        )
                    )
                )
                return

            self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except ClientDisconnected:
            return
        except Exception as error:
            try:
                self.send_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            except ClientDisconnected:
                return

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path

        try:
            if path == "/config/user-context":
                body = self.read_json()
                try:
                    config = update_user_context(body)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return

                self.send_json(config_to_json(config))
                return

            if path == "/config/dreaming":
                body = self.read_json()
                config = update_dreaming_config(body)
                self.send_json(config_to_json(config))
                return

            if path == "/config/chat":
                body = self.read_json()
                config = update_chat_config(body)
                self.send_json(config_to_json(config))
                return

            if path == "/config/autonomy":
                body = self.read_json()
                config = update_autonomy_config(body)
                self.send_json(config_to_json(config))
                return

            if path == "/config/mcp":
                body = self.read_json()
                config = update_mcp_config(body)
                self.send_json(config_to_json(config))
                return

            if path == "/config/model-runtime":
                body = self.read_json()
                try:
                    config = update_model_runtime_config(body)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return

                self.send_json(config_to_json(config))
                return

            if path == "/self":
                self.send_json(update_self_state(self.read_json()))
                return

            if path.startswith("/goals/"):
                raw_id = unquote(path.removeprefix("/goals/").strip("/"))
                try:
                    self.send_json(update_goal(int(raw_id), self.read_json()).__dict__)
                except (ValueError, TypeError) as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                return

            if path.startswith("/skills/"):
                skill_name = unquote(path.removeprefix("/skills/").strip("/"))
                body = self.read_json()
                old_text = body.get("old_text") if isinstance(body.get("old_text"), str) else ""
                new_text = body.get("new_text") if isinstance(body.get("new_text"), str) else ""
                try:
                    self.send_json(skill_to_json(patch_skill(skill_name, old_text, new_text), include_content=True))
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                return

            if path.startswith("/memory/"):
                memory_id = unquote(path.removeprefix("/memory/").strip("/"))
                body = self.read_json()
                memory = update_generic_memory(
                    memory_id,
                    title=body.get("title") if isinstance(body.get("title"), str) else None,
                    summary=body.get("summary") if isinstance(body.get("summary"), str) else None,
                    kind=body.get("kind") if isinstance(body.get("kind"), str) else None,
                    importance=int(body["importance"]) if "importance" in body else None,
                    project_id=body.get("project_id") if isinstance(body.get("project_id"), str) else None,
                    emotional_tone=body.get("emotional_tone") if isinstance(body.get("emotional_tone"), str) else None,
                    source=body.get("source") if isinstance(body.get("source"), str) else None,
                    tags=body.get("tags") if isinstance(body.get("tags"), list) else None,
                    metadata_patch=body.get("metadata_patch") if isinstance(body.get("metadata_patch"), dict) else None,
                )
                self.send_json(memory_to_json(memory))
                return
            self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except ClientDisconnected:
            return
        except Exception as error:
            try:
                self.send_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            except ClientDisconnected:
                return

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path

        try:
            if path.startswith("/chats/") and path.endswith("/turn"):
                chat_id, message_id = parse_chat_message_path(path, suffix="turn")
                if not chat_id or message_id <= 0:
                    self.send_json({"error": "Invalid chat message path."}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    self.send_json(delete_chat_message_turn(chat_id, message_id))
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                return

            if path.startswith("/chats/"):
                chat_id = unquote(path.removeprefix("/chats/").strip("/"))
                deleted = delete_chat(chat_id)
                self.send_json({"deleted": deleted}, status=HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND)
                return

            if path.startswith("/projects/"):
                project_id = unquote(path.removeprefix("/projects/").strip("/"))
                deleted = unregister_project(project_id)
                self.send_json({"deleted": deleted}, status=HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND)
                return

            if path.startswith("/notifications/"):
                notification_id = parse_notification_id(path)
                if notification_id <= 0:
                    self.send_json({"error": "Invalid notification id."}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"dismissed": dismiss_notification(notification_id), "unread_count": unread_notification_count()})
                return

            self.send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except ClientDisconnected:
            return
        except Exception as error:
            try:
                self.send_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            except ClientDisconnected:
                return

    def stream_chat(self, body: dict[str, Any]) -> None:
        messages = body.get("messages")

        if not isinstance(messages, list):
            self.send_json({"error": "messages must be a list"}, status=HTTPStatus.BAD_REQUEST)
            return

        self.send_response(HTTPStatus.OK)
        self.send_common_headers(content_type="text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        model = body.get("model") if isinstance(body.get("model"), str) else None
        mode = body.get("mode") if isinstance(body.get("mode"), str) else "chat"
        chat_id = body.get("chat_id") if isinstance(body.get("chat_id"), str) else ""
        resume = bool(body.get("resume"))
        thinking_enabled = bool(body.get("thinking_enabled"))
        latest_user_text = latest_user_message(messages)

        if not chat_id and not latest_user_text:
            self.write_sse(
                {
                    "kind": "error",
                    "text": "Write a message before starting a new chat.",
                    "done": True,
                }
            )
            return

        if not chat_id:
            chat = create_chat(title_from_text(latest_user_text), mode)
            chat_id = chat.id
            self.write_sse({"kind": "chat", "chat_id": chat.id, "title": chat.title})

        try:
            chat_summary = get_chat(chat_id)
            self.write_sse(
                {
                    "kind": "chat",
                    "chat_id": chat_id,
                    "title": chat_summary.get("title", ""),
                }
            )
        except Exception:
            pass

        existing_run = active_chat_run(chat_id)

        if existing_run is not None:
            self.stream_active_run(existing_run)
            return

        if resume:
            self.write_sse({"done": True})
            return

        previous_lifecycle = get_lifecycle_state()
        greeting_text = return_greeting_text(previous_lifecycle.last_user_activity_at, latest_user_text, load_config())
        record_user_activity(chat_id=chat_id, text=latest_user_text)
        record_continuity_event(
            "user_message_received",
            latest_user_text,
            source="chat",
            chat_id=chat_id,
            topic=title_from_text(latest_user_text),
        )

        replace_chat_messages(chat_id, messages, mode)

        run = ActiveChatRun(
            chat_id=chat_id,
            mode=mode,
            model=model,
            prompt_messages=build_chat_messages(messages, mode, chat_id=chat_id),
            thinking_enabled=thinking_enabled,
            return_greeting_text=greeting_text,
        )

        register_chat_run(run)

        subscriber = run.subscribe()
        start_chat_run(run)

        self.stream_subscriber(run, subscriber)
        _detect_personality_signals(latest_user_text, chat_id)

    def cancel_chat(self, body: dict[str, Any]) -> None:
        chat_id = body.get("chat_id") if isinstance(body.get("chat_id"), str) else ""

        if not chat_id:
            self.send_json({"error": "chat_id is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        run = active_chat_run(chat_id)

        if run is None or run.status != "running":
            self.send_json({"cancelled": False})
            return

        run.cancel()
        log_activity("chat.cancelled", "Stopped active chat response", {"chat_id": chat_id})
        self.send_json({"cancelled": True})

    def permission(self, body: dict[str, Any]) -> None:
        chat_id = body.get("chat_id") if isinstance(body.get("chat_id"), str) else ""
        granted = bool(body.get("granted"))

        if not chat_id:
            self.send_json({"error": "chat_id is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        run = active_chat_run(chat_id)

        if run is None or run.status != "running":
            self.send_json({"error": "No active run found for this chat"}, status=HTTPStatus.NOT_FOUND)
            return

        with run.lock:
            if run.permission_request is None:
                self.send_json({"error": "No pending permission request"}, status=HTTPStatus.BAD_REQUEST)
                return

            run.permission_granted = granted
            run.permission_response.set()

        self.send_json({"ok": True})

    def stream_active_run(self, run: ActiveChatRun) -> None:
        subscriber = run.subscribe()
        self.stream_subscriber(run, subscriber)

    def stream_subscriber(self, run: ActiveChatRun, subscriber: Any) -> None:
        try:
            while True:
                try:
                    event = subscriber.get(timeout=STREAM_HEARTBEAT_SECONDS)
                except queue.Empty:
                    self.write_sse({"kind": "heartbeat"})
                    continue

                self.write_sse(event)

                if event.get("done"):
                    return
        except ClientDisconnected:
            return
        finally:
            run.unsubscribe(subscriber)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))

        if length == 0:
            return {}

        raw = self.rfile.read(length).decode("utf-8")

        return json.loads(raw)

    def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(data, indent=2).encode("utf-8")

        self.send_response(status)
        self.send_common_headers(content_type="application/json")
        self.send_header("Content-Length", str(len(encoded)))

        try:
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError) as error:
            raise ClientDisconnected() from error

    def write_sse(self, data: dict[str, Any]) -> None:
        try:
            self.wfile.write(f"data: {json.dumps(data)}\n\n".encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise ClientDisconnected() from error

    def send_common_headers(self, content_type: str = "text/plain") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")


def _episode_to_json(episode: Episode) -> dict[str, Any]:
    return {
        "id": episode.id,
        "created_at": episode.created_at,
        "updated_at": episode.updated_at,
        "conversation_id": episode.conversation_id,
        "project_id": episode.project_id,
        "type": episode.type,
        "title": episode.title,
        "summary": episode.summary,
        "importance": episode.importance,
        "emotional_tone": episode.emotional_tone,
        "source": episode.source,
        "tags": episode.tags,
        "metadata": episode.metadata,
    }


def parse_chat_message_path(path: str, suffix: str) -> tuple[str, int]:
    parts = [unquote(part) for part in path.strip("/").split("/")]
    if len(parts) != 5 or parts[0] != "chats" or parts[2] != "messages" or parts[4] != suffix:
        return "", 0
    try:
        message_id = int(parts[3])
    except ValueError:
        return "", 0
    return parts[1], message_id


def parse_notification_id(path: str, suffix: str = "") -> int:
    parts = [unquote(part) for part in path.strip("/").split("/")]
    expected_length = 3 if suffix else 2
    if len(parts) != expected_length or parts[0] != "notifications":
        return 0
    if suffix and parts[2] != suffix:
        return 0
    try:
        return int(parts[1])
    except ValueError:
        return 0


def config_to_json(config: BitBuddyConfig) -> dict[str, Any]:
    selected_personality = load_selected_personality(config.personality)
    return {
        "name": config.name,
        "config_path": str(CONFIG_PATH),
        "personalities_dir": str(PERSONALITIES_DIR),
        "legacy_personality_path": str(PERSONALITY_PATH),
        "provider": {
            "type": config.provider.type,
            "url": config.provider.url,
            "model": config.provider.model,
        },
        "runtime": {
            "project_scan_interval_seconds": config.project_scan_interval_seconds,
        },
        "mcp": {
            "enabled": config.mcp.enabled,
        },
        "mcp_servers": {
            server.name: {
                "command": server.command,
                "args": list(server.args),
                "timeout": server.timeout,
                "connect_timeout": server.connect_timeout,
                "enabled": server.enabled,
            }
            for server in config.mcp_servers
        },
        "user_context": {
            "location_label": config.user_context.location_label,
            "timezone": config.user_context.timezone,
            "locale": config.user_context.locale,
        },
        "chat": {
            "return_greeting_enabled": config.chat.return_greeting_enabled,
            "return_greeting_idle_minutes": config.chat.return_greeting_idle_minutes,
            "return_greeting_phrases": list(config.chat.return_greeting_phrases),
            "max_tool_rounds": config.chat.max_tool_rounds,
        },
        "autonomy": {
            "enabled": config.autonomy.enabled,
            "run_after_idle_consolidation": config.autonomy.run_after_idle_consolidation,
            "idle_delay_seconds": config.autonomy.idle_delay_seconds,
            "repeat_idle_cycles": config.autonomy.repeat_idle_cycles,
            "idle_backoff_multiplier": config.autonomy.idle_backoff_multiplier,
            "idle_max_delay_seconds": config.autonomy.idle_max_delay_seconds,
            "max_actions_per_cycle": config.autonomy.max_actions_per_cycle,
            "max_pending_questions": config.autonomy.max_pending_questions,
            "max_pending_comments": config.autonomy.max_pending_comments,
            "max_new_questions_per_cycle": config.autonomy.max_new_questions_per_cycle,
            "max_autonomous_deliveries_per_day": config.autonomy.max_autonomous_deliveries_per_day,
            "web_search": {
                "enabled": config.autonomy.web_search.enabled,
                "provider": config.autonomy.web_search.provider,
                "url": config.autonomy.web_search.url,
                "startup_command": config.autonomy.web_search.startup_command,
                "max_results": config.autonomy.web_search.max_results,
            },
        },
        "dreaming": {
            "enabled": config.dreaming.enabled,
            "bedtime": config.dreaming.bedtime,
            "wake_time": config.dreaming.wake_time,
            "goodnight_triggers": list(config.dreaming.goodnight_triggers),
            "goodmorning_triggers": list(config.dreaming.goodmorning_triggers),
            "idle_before_dream_minutes": config.dreaming.idle_before_dream_minutes,
            "minimum_dream_window_minutes": config.dreaming.minimum_dream_window_minutes,
            "max_dream_tasks_per_night": config.dreaming.max_dream_tasks_per_night,
            "allow_post_dream_autonomy_rounds": config.dreaming.allow_post_dream_autonomy_rounds,
            "soft_delete_memories": config.dreaming.soft_delete_memories,
            "quiet_mode_after_bedtime": config.dreaming.quiet_mode_after_bedtime,
            "goodnight_immediate_winddown": config.dreaming.goodnight_immediate_winddown,
            "stale_intention_days": config.dreaming.stale_intention_days,
            "low_priority_stale_intention_days": config.dreaming.low_priority_stale_intention_days,
            "self_note_injection_enabled": config.dreaming.self_note_injection_enabled,
        },
        "presentation": {
            "style": config.presentation.style,
            "pronouns": config.presentation.pronouns,
        },
        "personality": {
            "source": config.personality.source,
            "id": config.personality.id,
            "path": config.personality.path,
            "expressiveness": config.personality.expressiveness,
            "proactivity": config.personality.proactivity,
            "quirk_frequency": config.personality.quirk_frequency,
            "display_name": selected_personality.display_name,
            "dislikes": selected_personality.dislikes,
        },
    }


def mcp_status_to_json(message: str = "", doctor: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    status = computer_use_linux_status()
    configured = any(server.name == "computer_use_linux" for server in config.mcp_servers)
    payload: dict[str, Any] = {
        "mcp": {"enabled": config.mcp.enabled},
        "computer_use_linux": {
            "configured": configured,
            "available": status.available,
            "path": status.path,
            "source": status.source,
            "message": status.message,
        },
        "mcp_servers": {
            server.name: {
                "command": server.command,
                "args": list(server.args),
                "timeout": server.timeout,
                "connect_timeout": server.connect_timeout,
                "enabled": server.enabled,
            }
            for server in config.mcp_servers
        },
    }
    if message:
        payload["message"] = message
    if doctor is not None:
        payload["doctor"] = doctor
    return payload


_SIGNAL_PATTERNS: list[tuple[str, str]] = [
    ("correction", "User corrected BitBuddy: "),
    ("preference", "User expressed a preference: "),
    ("style", "User signalled a style preference: "),
]

_CORRECTION_PHRASES = ("actually,", "actually ", "no, that's", "not quite", "that's wrong", "i meant ", "you misunderstood", "no not that", "that's not right", "that's not what")
_PREFERENCE_PHRASES = ("i prefer ", "i like when you", "please don't", "stop doing", "i'd rather", "i want you to", "don't do that", "i don't like when")
_STYLE_PHRASES = ("shorter", "more concise", "less formal", "simpler responses", "too long", "be more brief", "don't over-explain", "just give me", "stop explaining")


def _detect_personality_signals(user_text: str, chat_id: str) -> None:
    if not user_text or len(user_text) < 8:
        return
    lowered = user_text.lower().strip()
    snippet = user_text.strip()[:200]
    try:
        if any(lowered.startswith(p) or f" {p}" in lowered for p in _CORRECTION_PHRASES):
            record_conversation_signal(f"User corrected or redirected BitBuddy: {snippet}", chat_id)
        elif any(p in lowered for p in _PREFERENCE_PHRASES):
            record_conversation_signal(f"User expressed a preference: {snippet}", chat_id)
        elif any(p in lowered for p in _STYLE_PHRASES):
            record_conversation_signal(f"User signalled a style or response preference: {snippet}", chat_id)
    except Exception:
        pass


def list_subagent_runs(limit: int = 20) -> list[dict[str, Any]]:
    import sqlite3
    from .paths import GLOBAL_DB_PATH
    try:
        with sqlite3.connect(GLOBAL_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            run_rows = conn.execute(
                "select id, agent_type, task, status, created_at, completed_at, report, error, metadata from subagent_runs order by created_at desc limit ?",
                (limit,),
            ).fetchall()
            if not run_rows:
                return []
            run_ids = [row["id"] for row in run_rows]
            placeholders = ",".join("?" for _ in run_ids)
            step_rows = conn.execute(
                f"select run_id, sequence, tool, status, summary, metadata, created_at from subagent_steps where run_id in ({placeholders}) order by run_id, sequence",
                run_ids,
            ).fetchall()
    except Exception:
        return []

    steps_by_run: dict[str, list[dict[str, Any]]] = {}
    for step in step_rows:
        run_id = step["run_id"]
        steps_by_run.setdefault(run_id, []).append({
            "sequence": step["sequence"],
            "tool": step["tool"],
            "status": step["status"],
            "summary": step["summary"],
        })

    result = []
    for row in run_rows:
        run_id = row["id"]
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except Exception:
            metadata = {}
        result.append({
            "id": run_id,
            "agent_type": row["agent_type"],
            "task": row["task"],
            "status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "report": row["report"],
            "error": row["error"],
            "metadata": metadata,
            "steps": steps_by_run.get(run_id, []),
        })
    return result
