from __future__ import annotations

import base64
import hashlib
import json
import queue
import secrets as py_secrets
import shutil
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse
import urllib.error
import urllib.request

from .auth import API_TOKEN_HEADER, is_allowed_origin, valid_api_token
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
from .config import BitBuddyConfig, ProviderConfig, load_config, load_personality, update_autonomy_config, update_calendar_config, update_chat_config, update_dreaming_config, update_email_config, update_mcp_config, update_model_runtime_config, update_personality_config, update_user_context, upsert_mcp_server
from .database import db_connection
from .calendar.permissions import CALENDAR_SCOPES, CalendarPermissionRequired, all_permissions as calendar_permissions, set_permission as set_calendar_permission
from .calendar.providers import EventDraft, EventPatch
from .calendar.secrets import get_credentials, put_credentials, delete_credentials
from .calendar.service import calendar_overview, create_event as calendar_create_event, delete_event as calendar_delete_event, modify_event as calendar_modify_event, user_timezone, view_events as calendar_view_events
from .calendar.store import calendar_to_json, ensure_default_calendar, event_to_json, list_calendars as list_calendars_store
from .email.models import mailbox_to_json, message_page_to_json, message_to_json, rule_to_json
from .email.permissions import EMAIL_SCOPES, EmailPermissionRequired, all_permissions as email_permissions, set_permission as set_email_permission
from .email.service import create_sender_trash_rule as email_create_sender_trash_rule, delete_message as email_delete_message, delete_rule as email_delete_rule, email_account_id, email_overview, empty_trash as email_empty_trash, list_mailboxes as email_list_mailboxes, list_messages_page as email_list_messages_page, list_rules as email_list_rules, read_message as email_read_message, search_messages_page as email_search_messages_page, trash_message as email_trash_message
from .continuity import record_continuity_event
from .personality import BUILTIN_PERSONALITIES, list_available_personalities, load_selected_personality, selected_personality_to_legacy_dict
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
from .notifications import dismiss_notification, list_notifications, mark_all_notifications_read, mark_notification_read, notification_to_json, subscribe_notifications, unread_notification_count, unsubscribe_notifications
from .self_model import add_self_journal, create_goal, get_self_state, list_goals, record_conversation_signal, record_personality_quirks, update_goal, update_self_state
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
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_REDIRECT_URI = "http://localhost:1455/auth/callback"
CODEX_SCOPE = "openid profile email offline_access"
CODEX_SECRET_REF = "provider:codex:oauth"
CODEX_AUTH_FLOWS: dict[str, dict[str, str]] = {}
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_FULL_MAIL_SCOPE = "https://mail.google.com/"
GMAIL_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8787/email/gmail/callback"
GMAIL_LEGACY_LOCALHOST_REDIRECT_URI = "http://localhost:8787/email/gmail/callback"
GMAIL_AUTH_FLOWS: dict[str, dict[str, str]] = {}
GMAIL_OAUTH_DIAGNOSTICS: dict[str, str] = {}
GMAIL_OAUTH_FLOW_TTL_SECONDS = 900
PUBLIC_PATHS = {"/health", "/provider/codex/callback", "/email/gmail/callback"}


class BitBuddyRequestHandler(BaseHTTPRequestHandler):
    server_version = "BitBuddy/0.1"

    def do_OPTIONS(self) -> None:
        if not self.origin_allowed():
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_common_headers()
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_common_headers()
        self.end_headers()

    def handle_codex_callback(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]
        try:
            exchange_codex_code(code, state)
        except ValueError as error:
            self.send_html(codex_callback_html("Codex authorization failed", str(error), ok=False), status=HTTPStatus.BAD_REQUEST)
            return
        self.send_html(codex_callback_html("Codex connected", "BitBuddy is authorized for Codex. You can close this tab and return to Settings.", ok=True))

    def handle_gmail_callback(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]
        error = (params.get("error") or [""])[0]
        error_description = (params.get("error_description") or [""])[0]
        try:
            complete_gmail_callback(code=code, state=state, google_error=error, google_error_description=error_description, callback_source="web")
        except ValueError as error:
            self.send_html(codex_callback_html("Gmail authorization failed", str(error), ok=False), status=HTTPStatus.BAD_REQUEST)
            return
        self.send_html(codex_callback_html("Gmail connected", "BitBuddy is authorized for Gmail read/search and Trash access. You can close this tab and return to Settings.", ok=True))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if not self.authorize_request(path):
            return

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

            if path == "/provider/codex/status":
                self.send_json(codex_oauth_status())
                return

            if path == "/provider/codex/callback":
                self.handle_codex_callback()
                return

            if path == "/email/gmail/callback":
                self.handle_gmail_callback()
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

            if path == "/calendar/overview":
                self.send_json(calendar_overview())
                return

            if path == "/calendar/events":
                params = parse_qs(urlparse(self.path).query)
                range_str = params.get("range", [""])[0]
                start = params.get("start", [""])[0]
                end = params.get("end", [""])[0]
                tz = user_timezone()
                events = calendar_view_events(range_str=range_str, start=start, end=end, enforce=False)
                self.send_json({"timezone": tz, "events": [event_to_json(event) for event in events]})
                return

            if path == "/calendar/calendars":
                account, _calendar = ensure_default_calendar(user_timezone())
                self.send_json({"calendars": [calendar_to_json(c) for c in list_calendars_store(account.id)]})
                return

            if path == "/calendar/permissions":
                account, _calendar = ensure_default_calendar(user_timezone())
                self.send_json({"scopes": list(CALENDAR_SCOPES), "permissions": calendar_permissions(account.id)})
                return

            if path == "/email/overview":
                self.send_json(email_overview())
                return

            if path == "/email/gmail/status":
                self.send_json(gmail_oauth_status())
                return

            if path == "/email/permissions":
                account = email_account_id()
                self.send_json({"scopes": list(EMAIL_SCOPES), "permissions": email_permissions(account)})
                return

            if path == "/email/rules":
                self.send_json({"rules": [rule_to_json(rule) for rule in email_list_rules()]})
                return

            if path == "/email/mailboxes":
                try:
                    mailboxes = email_list_mailboxes(enforce=False)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"mailboxes": [mailbox_to_json(mailbox) for mailbox in mailboxes]})
                return

            if path == "/email/messages":
                params = parse_qs(urlparse(self.path).query)
                mailbox = params.get("mailbox", [""])[0]
                page_token = params.get("page_token", [""])[0]
                try:
                    limit = int(params.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                try:
                    page = email_list_messages_page(mailbox=mailbox, limit=limit, page_token=page_token, enforce=False)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(message_page_to_json(page))
                return

            if path == "/email/search":
                params = parse_qs(urlparse(self.path).query)
                query = params.get("q", [""])[0]
                mailbox = params.get("mailbox", [""])[0]
                page_token = params.get("page_token", [""])[0]
                try:
                    limit = int(params.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                try:
                    page = email_search_messages_page(query=query, mailbox=mailbox, limit=limit, page_token=page_token, enforce=False)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(message_page_to_json(page))
                return

            if path == "/email/message":
                params = parse_qs(urlparse(self.path).query)
                message_id = params.get("id", [""])[0]
                mailbox = params.get("mailbox", [""])[0]
                try:
                    message = email_read_message(message_id=message_id, mailbox=mailbox, enforce=False)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"message": message_to_json(message, include_body=True)})
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

            if path == "/notifications/stream":
                self.stream_notifications()
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
        if not self.authorize_request(path):
            return

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

            if path == "/calendar/events":
                body = self.read_json()
                title = str(body.get("title") or "").strip()
                start = str(body.get("start") or "").strip()
                end = str(body.get("end") or "").strip()
                if not title or not start or not end:
                    self.send_json({"error": "title, start, and end are required."}, status=HTTPStatus.BAD_REQUEST)
                    return
                draft = EventDraft(
                    title=title,
                    start_at=start,
                    end_at=end,
                    description=str(body.get("description") or ""),
                    location=str(body.get("location") or ""),
                    all_day=bool(body.get("all_day", False)),
                    attendees=[str(a) for a in body.get("attendees", []) if isinstance(a, str)],
                    source="user",
                )
                try:
                    event, conflicts = calendar_create_event(draft, enforce=False)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(
                    {"event": event_to_json(event), "conflicts": [event_to_json(c) for c in conflicts]},
                    status=HTTPStatus.CREATED,
                )
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
                body = self.read_json()
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

            if path == "/email/message/trash":
                body = self.read_json()
                message_id = str(body.get("message_id") or body.get("id") or "").strip()
                mailbox = str(body.get("mailbox") or "").strip()
                try:
                    message = email_trash_message(message_id=message_id, mailbox=mailbox, enforce=True)
                except (EmailPermissionRequired, ValueError) as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"message": message_to_json(message), "trashed": True})
                return

            if path == "/email/message/delete":
                body = self.read_json()
                message_id = str(body.get("message_id") or body.get("id") or "").strip()
                mailbox = str(body.get("mailbox") or "TRASH").strip()
                confirm = str(body.get("confirm") or "")
                try:
                    message = email_delete_message(message_id=message_id, mailbox=mailbox, enforce=True, confirm=confirm)
                except (EmailPermissionRequired, ValueError) as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"message": message_to_json(message), "deleted": True})
                return

            if path == "/email/trash/empty":
                body = self.read_json()
                if str(body.get("confirm") or "") != "EMPTY_TRASH":
                    self.send_json({"error": "Empty Trash requires confirm=EMPTY_TRASH."}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    deleted = email_empty_trash(enforce=True)
                except (EmailPermissionRequired, ValueError) as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"emptied": True, "deleted": deleted})
                return

            if path == "/email/rules/sender-trash":
                body = self.read_json()
                sender = str(body.get("sender") or "").strip()
                mailbox = str(body.get("mailbox") or "INBOX").strip()
                apply_existing = bool(body.get("apply_existing", False))
                try:
                    rule, applied = email_create_sender_trash_rule(sender=sender, apply_existing=apply_existing, mailbox=mailbox)
                except (EmailPermissionRequired, ValueError) as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"rule": rule_to_json(rule), "applied": applied}, status=HTTPStatus.CREATED)
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

            if path == "/provider/models":
                try:
                    self.send_json({"models": draft_provider_client(self.read_json()).models()})
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
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

            if path == "/provider/codex/login":
                body = self.read_json()
                self.send_json(start_codex_login(force=bool(body.get("force", False))))
                return

            if path == "/provider/codex/complete":
                body = self.read_json()
                try:
                    code, state = parse_codex_authorization_input(str(body.get("input") or ""))
                    exchange_codex_code(code, state)
                except ValueError as error:
                    self.send_json({"ok": False, "connected": False, "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(codex_oauth_status())
                return

            if path == "/provider/codex/logout":
                delete_credentials(CODEX_SECRET_REF)
                self.send_json({"ok": True, "message": "Codex authorization removed from BitBuddy."})
                return

            if path == "/email/gmail/login":
                body = self.read_json()
                self.send_json(start_gmail_login(force=bool(body.get("force", False))))
                return

            if path in {"/email/gmail/open-clean-browser", "/email/gmail/open-clean-firefox"}:
                body = self.read_json()
                self.send_json(open_gmail_clean_browser(force=bool(body.get("force", False))))
                return

            if path == "/email/gmail/complete":
                body = self.read_json()
                try:
                    code, state = parse_gmail_authorization_input(str(body.get("input") or ""))
                    complete_gmail_callback(code=code, state=state, callback_source="manual")
                except ValueError as error:
                    self.send_json({"ok": False, "connected": False, "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(gmail_oauth_status())
                return

            if path == "/email/gmail/logout":
                config = load_config().email
                delete_credentials(config.gmail_token_ref)
                self.send_json({"ok": True, "connected": False, "message": "Gmail authorization removed from BitBuddy."})
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
        if not self.authorize_request(path):
            return

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

            if path == "/config/personality":
                body = self.read_json()
                config = update_personality_config(body)
                try:
                    record_personality_quirks(
                        config.personality.id,
                        list(config.personality.bitbuddy_likes),
                        list(config.personality.bitbuddy_dislikes),
                    )
                except Exception:
                    pass
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

            if path == "/config/calendar":
                body = self.read_json()
                config = update_calendar_config(body)
                self.send_json(config_to_json(config))
                return

            if path == "/config/email":
                body = self.read_json()
                password = str(body.pop("password", "") or "")
                gmail_client_secret = str(body.pop("gmail_client_secret", "") or "")
                if password:
                    ref = str(body.get("credentials_ref") or "").strip()
                    if not ref:
                        identity = str(body.get("email_address") or body.get("username") or "default").strip().casefold() or "default"
                        ref = f"email:{identity}:imap"
                    put_credentials(ref, {"password": password})
                    body["credentials_ref"] = ref
                if gmail_client_secret:
                    ref = str(body.get("gmail_credentials_ref") or "").strip()
                    if not ref:
                        identity = str(body.get("email_address") or "default").strip().casefold() or "default"
                        ref = f"email:gmail:{identity}:client"
                    put_credentials(ref, {"client_secret": gmail_client_secret})
                    body["gmail_credentials_ref"] = ref
                if str(body.get("provider") or "").strip().lower() == "gmail" and not str(body.get("gmail_token_ref") or "").strip():
                    identity = str(body.get("email_address") or "default").strip().casefold() or "default"
                    body["gmail_token_ref"] = f"email:gmail:{identity}:tokens"
                config = update_email_config(body)
                self.send_json(config_to_json(config))
                return

            if path == "/calendar/permissions":
                body = self.read_json()
                scope = str(body.get("scope") or "")
                state = str(body.get("state") or "")
                account, _calendar = ensure_default_calendar(user_timezone())
                try:
                    permissions = set_calendar_permission(account.id, scope, state)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"permissions": permissions})
                return

            if path == "/email/permissions":
                body = self.read_json()
                scope = str(body.get("scope") or "")
                state = str(body.get("state") or "")
                account = email_account_id()
                try:
                    permissions = set_email_permission(account, scope, state)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self.send_json({"permissions": permissions})
                return

            if path.startswith("/calendar/events/"):
                event_id = unquote(path.removeprefix("/calendar/events/").strip("/"))
                if not event_id or "/" in event_id:
                    self.send_json({"error": "Invalid event id."}, status=HTTPStatus.BAD_REQUEST)
                    return
                body = self.read_json()
                patch = EventPatch(
                    title=str(body["title"]) if "title" in body else None,
                    start_at=str(body["start"]) if "start" in body else None,
                    end_at=str(body["end"]) if "end" in body else None,
                    description=str(body["description"]) if "description" in body else None,
                    location=str(body["location"]) if "location" in body else None,
                    all_day=bool(body["all_day"]) if "all_day" in body else None,
                    status=str(body["status"]) if "status" in body else None,
                )
                try:
                    event, conflicts = calendar_modify_event(event_id, patch, enforce=False)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.NOT_FOUND)
                    return
                self.send_json({"event": event_to_json(event), "conflicts": [event_to_json(c) for c in conflicts]})
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
        if not self.authorize_request(path):
            return

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

            if path.startswith("/calendar/events/"):
                event_id = unquote(path.removeprefix("/calendar/events/").strip("/"))
                if not event_id or "/" in event_id:
                    self.send_json({"error": "Invalid event id."}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    event = calendar_delete_event(event_id, enforce=False)
                except ValueError as error:
                    self.send_json({"error": str(error)}, status=HTTPStatus.NOT_FOUND)
                    return
                self.send_json({"deleted": True, "event": event_to_json(event)})
                return

            if path.startswith("/email/rules/"):
                raw_id = unquote(path.removeprefix("/email/rules/").strip("/"))
                try:
                    rule_id = int(raw_id)
                except ValueError:
                    self.send_json({"error": "Invalid email rule id."}, status=HTTPStatus.BAD_REQUEST)
                    return
                deleted = email_delete_rule(rule_id)
                self.send_json({"deleted": deleted}, status=HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND)
                return

            if path == "/email/gmail/client-secret":
                config = load_config().email
                delete_credentials(config.gmail_credentials_ref)
                self.send_json(gmail_oauth_status() | {"message": "Saved Gmail OAuth client secret removed from BitBuddy."})
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

    def stream_notifications(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_common_headers(content_type="text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        subscriber = subscribe_notifications()
        try:
            while True:
                try:
                    event = subscriber.get(timeout=STREAM_HEARTBEAT_SECONDS)
                except queue.Empty:
                    self.write_sse({"kind": "heartbeat"})
                    continue
                self.write_sse(event)
        except ClientDisconnected:
            return
        finally:
            unsubscribe_notifications(subscriber)

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

    def send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = html.encode("utf-8")
        self.send_response(status)
        self.send_common_headers(content_type="text/html; charset=utf-8")
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

    def origin_allowed(self) -> bool:
        return is_allowed_origin(self.headers.get("Origin", ""))

    def authorize_request(self, path: str) -> bool:
        if path in PUBLIC_PATHS:
            return True
        if not self.origin_allowed():
            self.send_json({"error": "Origin is not allowed."}, status=HTTPStatus.FORBIDDEN)
            return False
        if not valid_api_token(self.headers.get(API_TOKEN_HEADER, "")):
            self.send_json({"error": "BitBuddy API token is required."}, status=HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def send_common_headers(self, content_type: str = "text/plain") -> None:
        self.send_header("Content-Type", content_type)
        origin = self.headers.get("Origin", "")
        if origin and is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", f"content-type, {API_TOKEN_HEADER}")
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
            "has_api_key": config.provider.has_api_key,
        },
        "providers": [provider_to_json(provider) for provider in config.providers],
        "active_provider": config.active_provider,
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
            "activity_level": config.autonomy.activity_level,
            "idle_delay_seconds": config.autonomy.idle_delay_seconds,
            "repeat_idle_cycles": config.autonomy.repeat_idle_cycles,
            "idle_backoff_multiplier": config.autonomy.idle_backoff_multiplier,
            "idle_max_delay_seconds": config.autonomy.idle_max_delay_seconds,
            "max_actions_per_cycle": config.autonomy.max_actions_per_cycle,
            "max_steps_per_session": config.autonomy.max_steps_per_session,
            "max_pending_questions": config.autonomy.max_pending_questions,
            "max_pending_comments": config.autonomy.max_pending_comments,
            "max_new_questions_per_cycle": config.autonomy.max_new_questions_per_cycle,
            "max_autonomous_deliveries_per_day": config.autonomy.max_autonomous_deliveries_per_day,
            "surface_cooldown_minutes": config.autonomy.surface_cooldown_minutes,
            "spontaneous_remark_cooldown_minutes": config.autonomy.spontaneous_remark_cooldown_minutes,
            "min_autonomous_priority": config.autonomy.min_autonomous_priority,
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
        "calendar": {
            "enabled": config.calendar.enabled,
            "default_provider": config.calendar.default_provider,
            "reminder_upcoming_minutes": config.calendar.reminder_upcoming_minutes,
            "reminder_starting_soon_minutes": config.calendar.reminder_starting_soon_minutes,
            "urgent_interrupts_enabled": config.calendar.urgent_interrupts_enabled,
            "urgent_interrupt_persistent": config.calendar.urgent_interrupt_persistent,
            "conflict_warnings_enabled": config.calendar.conflict_warnings_enabled,
            "free_day_summary_enabled": config.calendar.free_day_summary_enabled,
            "chat_nudges_enabled": config.calendar.chat_nudges_enabled,
            "scheduler_tick_seconds": config.calendar.scheduler_tick_seconds,
            "holidays_enabled": config.calendar.holidays_enabled,
            "holidays_country": config.calendar.holidays_country,
        },
        "email": {
            "enabled": config.email.enabled,
            "provider": config.email.provider,
            "account_label": config.email.account_label,
            "email_address": config.email.email_address,
            "imap_host": config.email.imap_host,
            "imap_port": config.email.imap_port,
            "imap_security": config.email.imap_security,
            "username": config.email.username,
            "credentials_ref": config.email.credentials_ref,
            "gmail_oauth_mode": config.email.gmail_oauth_mode,
            "gmail_client_id": config.email.gmail_client_id,
            "gmail_credentials_ref": config.email.gmail_credentials_ref,
            "gmail_token_ref": config.email.gmail_token_ref,
            "gmail_redirect_uri": config.email.gmail_redirect_uri,
            "gmail_full_mail_access": config.email.gmail_full_mail_access,
            "default_mailbox": config.email.default_mailbox,
            "max_preview_messages": config.email.max_preview_messages,
            "tool_message_limit": config.email.tool_message_limit,
            "has_password": bool(config.email.credentials_ref),
            "has_gmail_client_secret": bool(get_credentials(config.email.gmail_credentials_ref).get("client_secret")),
            "gmail_connected": bool(get_credentials(config.email.gmail_token_ref).get("refresh_token")),
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
            "bitbuddy_likes": list(config.personality.bitbuddy_likes),
            "bitbuddy_dislikes": list(config.personality.bitbuddy_dislikes),
            "display_name": selected_personality.display_name,
            "dislikes": selected_personality.dislikes,
        },
        "available_personalities": [
            {
                "id": profile.id,
                "display_name": profile.display_name,
                "description": profile.description,
                "source": "builtin" if profile.id in BUILTIN_PERSONALITIES else "user",
            }
            for profile in list_available_personalities()
        ],
    }


def provider_to_json(provider: Any) -> dict[str, Any]:
    return {
        "key": provider.key,
        "type": provider.type,
        "url": provider.url,
        "model": provider.model,
        "has_api_key": provider.has_api_key,
    }


def draft_provider_client(body: dict[str, Any]) -> ProviderClient:
    provider_type = str(body.get("type") or "").strip()
    if not provider_type:
        raise ValueError("Provider type is required.")
    config = load_config()
    existing = next((provider for provider in config.providers if provider.type == provider_type), None)
    api_key = str(body.get("api_key") or "").strip() or (existing.api_key if existing else "")
    api_key_ref = existing.api_key_ref if existing else ""
    return ProviderClient(
        ProviderConfig(
            key=str(body.get("key") or provider_type),
            type=provider_type,
            url=str(body.get("url") or (existing.url if existing else "")).strip(),
            model=str(body.get("model") or (existing.model if existing else "")).strip(),
            api_key=api_key,
            api_key_ref=api_key_ref,
            has_api_key=bool(api_key or (existing.has_api_key if existing else False)),
        )
    )


def start_codex_login(force: bool = False) -> dict[str, Any]:
    status = codex_oauth_status()
    if status.get("ok") and not force:
        return {"ok": True, "connected": True, "message": status["message"], "auth_url": ""}
    if force:
        delete_credentials(CODEX_SECRET_REF)
    verifier = token_urlsafe(64)
    state = token_urlsafe(24)
    CODEX_AUTH_FLOWS[state] = {"verifier": verifier, "created_at": str(time.time())}
    auth_url = CODEX_AUTHORIZE_URL + "?" + urlencode(
        {
            "response_type": "code",
            "client_id": CODEX_CLIENT_ID,
            "redirect_uri": CODEX_REDIRECT_URI,
            "scope": CODEX_SCOPE,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "bitbuddy",
        }
    )
    callback_error = start_codex_callback_server()
    try:
        subprocess.Popen(["xdg-open", auth_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
    message = "Open the ChatGPT authorization page, allow BitBuddy, then return here and check status."
    callback_mode = "auto"
    if callback_error:
        message = f"Open the ChatGPT authorization page, approve access, then paste the final callback URL/code below. Auto-callback is unavailable: {callback_error}"
        callback_mode = "manual"
    return {
        "ok": True,
        "connected": False,
        "message": message,
        "auth_url": auth_url,
        "callback_mode": callback_mode,
        "device_code": "",
        "log_excerpt": "",
    }


def gmail_redirect_uri(config: Any | None = None) -> str:
    email_config = config or load_config().email
    uri = str(getattr(email_config, "gmail_redirect_uri", "") or "").strip()
    mode = str(getattr(email_config, "gmail_oauth_mode", "") or "desktop_pkce").strip()
    if mode == "desktop_pkce" and uri == GMAIL_LEGACY_LOCALHOST_REDIRECT_URI:
        return GMAIL_DEFAULT_REDIRECT_URI
    return uri or GMAIL_DEFAULT_REDIRECT_URI


def start_gmail_login(force: bool = False) -> dict[str, Any]:
    cleanup_expired_gmail_auth_flows()
    config = load_config().email
    status = gmail_oauth_status()
    redirect_uri = gmail_redirect_uri(config)
    oauth_mode = config.gmail_oauth_mode or "desktop_pkce"
    if status.get("ok") and not force:
        return {"ok": True, "connected": True, "message": status["message"], "auth_url": "", "redirect_uri": redirect_uri}
    if not config.gmail_client_id:
        return {"ok": False, "connected": False, "message": "Enter a Google OAuth desktop client ID in Email settings first.", "auth_url": "", "redirect_uri": redirect_uri}
    if oauth_mode == "web_secret" and not get_credentials(config.gmail_credentials_ref).get("client_secret"):
        return {"ok": False, "connected": False, "message": "Enter a Google OAuth client secret in Email settings first.", "auth_url": "", "redirect_uri": redirect_uri}
    if not config.gmail_token_ref:
        return {"ok": False, "connected": False, "message": "Save Email settings once before connecting Gmail.", "auth_url": "", "redirect_uri": redirect_uri}
    if force:
        delete_credentials(config.gmail_token_ref)
    state = token_urlsafe(24)
    verifier = token_urlsafe(64)
    prompt = "consent" if config.email_address else "select_account consent"
    access_type = "offline"
    scope = gmail_oauth_scope(config)
    GMAIL_AUTH_FLOWS[state] = {
        "created_at": str(time.time()),
        "token_ref": config.gmail_token_ref,
        "redirect_uri": redirect_uri,
        "mode": oauth_mode,
        "verifier": verifier,
    }

    auth_params = {
        "response_type": "code",
        "client_id": config.gmail_client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "access_type": access_type,
        "prompt": prompt,
        "state": state,
    }
    if config.email_address:
        auth_params["login_hint"] = config.email_address
    if oauth_mode == "desktop_pkce":
        auth_params["code_challenge"] = pkce_challenge(verifier)
        auth_params["code_challenge_method"] = "S256"
    GMAIL_OAUTH_DIAGNOSTICS["last_auth_url_params"] = json.dumps(
        {
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scope,
            "access_type": access_type,
            "prompt": prompt,
            "state_prefix": state[:8],
            "mode": oauth_mode,
            "pkce": oauth_mode == "desktop_pkce",
            "login_hint": config.email_address,
        },
        sort_keys=True,
    )
    GMAIL_OAUTH_DIAGNOSTICS["last_oauth_mode"] = oauth_mode
    log_activity(
        "gmail.oauth.start",
        "Starting Gmail OAuth flow",
        {
            "redirect_uri": redirect_uri,
            "scope": scope,
            "prompt": prompt,
            "access_type": access_type,
            "state_prefix": state[:8],
            "mode": oauth_mode,
        },
    )
    auth_url = GOOGLE_AUTHORIZE_URL + "?" + urlencode(auth_params)
    GMAIL_OAUTH_DIAGNOSTICS["last_redirect_uri"] = redirect_uri
    GMAIL_OAUTH_DIAGNOSTICS["last_auth_started_at"] = str(int(time.time()))
    GMAIL_OAUTH_DIAGNOSTICS["last_error"] = ""
    GMAIL_OAUTH_DIAGNOSTICS["last_google_error"] = ""
    GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "not_started"
    return {
        "ok": True,
        "connected": False,
        "message": "Open the Google authorization page, allow Gmail access, then return here and check status.",
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "oauth_mode": oauth_mode,
    }


def gmail_oauth_scope(config: object) -> str:
    return GMAIL_FULL_MAIL_SCOPE if bool(getattr(config, "gmail_full_mail_access", False)) else GMAIL_SCOPE


def cleanup_expired_gmail_auth_flows() -> None:
    now = time.time()
    expired: list[str] = []
    for state, flow in GMAIL_AUTH_FLOWS.items():
        try:
            created_at = float(flow.get("created_at") or "0")
        except ValueError:
            created_at = 0
        if created_at <= 0 or now - created_at > GMAIL_OAUTH_FLOW_TTL_SECONDS:
            expired.append(state)
    for state in expired:
        GMAIL_AUTH_FLOWS.pop(state, None)


def gmail_oauth_status() -> dict[str, Any]:
    config = load_config().email
    redirect_uri = gmail_redirect_uri(config)
    tokens = get_credentials(config.gmail_token_ref)
    connected = bool(tokens.get("refresh_token"))
    if connected:
        account = tokens.get("account_id") or config.email_address or "Gmail"
        return {"ok": True, "connected": True, "message": f"Connected to Gmail as {account}.", "redirect_uri": redirect_uri, "diagnostics": dict(GMAIL_OAUTH_DIAGNOSTICS)}
    configured = bool(config.gmail_client_id and (config.gmail_oauth_mode == "desktop_pkce" or get_credentials(config.gmail_credentials_ref).get("client_secret")))
    message = "Gmail OAuth client is configured. Connect Gmail to authorize mailbox access." if configured else "Gmail OAuth client is not configured."
    return {"ok": False, "connected": False, "message": message, "redirect_uri": redirect_uri, "diagnostics": dict(GMAIL_OAUTH_DIAGNOSTICS)}


def open_gmail_clean_browser(force: bool = False) -> dict[str, Any]:
    result = start_gmail_login(force=force)
    auth_url = str(result.get("auth_url") or "")
    if not auth_url:
        return result
    chromium = next(
        (
            path
            for path in (
                shutil.which("chromium"),
                shutil.which("chromium-browser"),
                shutil.which("google-chrome"),
                shutil.which("google-chrome-stable"),
                shutil.which("brave-browser"),
            )
            if path
        ),
        "",
    )
    if chromium:
        profile_dir = APP_DIR / "chromium-oauth-profiles" / token_urlsafe(8)
        profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(
                [
                    chromium,
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                    "--disable-sync",
                    "--new-window",
                    auth_url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            result["message"] = f"Could not open clean Chromium OAuth profile automatically: {error}. Falling back to Firefox."
        else:
            result["message"] = "Opened Gmail authorization in a disposable Chromium profile. Approve access there, then return here and check status."
            result["clean_browser"] = True
            result["clean_firefox"] = False
            result["browser"] = "chromium"
            result["profile_dir"] = str(profile_dir)
            return result
    profile_dir = APP_DIR / "firefox-oauth-profiles" / token_urlsafe(8)
    profile_dir.mkdir(parents=True, exist_ok=True)
    prefs = "\n".join(
        [
            'user_pref("browser.privatebrowsing.autostart", false);',
            'user_pref("browser.shell.checkDefaultBrowser", false);',
            'user_pref("extensions.enabledScopes", 0);',
            'user_pref("network.cookie.cookieBehavior", 0);',
            'user_pref("privacy.firstparty.isolate", false);',
            'user_pref("privacy.resistFingerprinting", false);',
            'user_pref("privacy.trackingprotection.enabled", false);',
            'user_pref("privacy.trackingprotection.pbmode.enabled", false);',
            "",
        ]
    )
    try:
        (profile_dir / "user.js").write_text(prefs, encoding="utf-8")
    except OSError as error:
        result["message"] = f"Could not prepare clean Firefox OAuth profile: {error}. Copy the auth URL manually."
        result["clean_firefox"] = False
        return result
    try:
        subprocess.Popen(["firefox", "--no-remote", "--profile", str(profile_dir), auth_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as error:
        result["message"] = f"Could not open clean Firefox OAuth profile automatically: {error}. Copy the auth URL manually."
        result["clean_firefox"] = False
        return result
    result["message"] = "Opened Gmail authorization in a disposable Firefox profile with tracking/fingerprinting protections disabled for this OAuth attempt. Approve access there, then return here and check status."
    result["clean_firefox"] = True
    result["profile_dir"] = str(profile_dir)
    return result


def open_gmail_clean_firefox(force: bool = False) -> dict[str, Any]:
    return open_gmail_clean_browser(force=force)


def complete_gmail_callback(*, code: str, state: str, google_error: str = "", google_error_description: str = "", callback_source: str = "") -> None:
    GMAIL_OAUTH_DIAGNOSTICS["last_callback_seen"] = json.dumps(
        {
            "source": callback_source,
            "has_code": bool(code),
            "state_prefix": state[:8] if state else "",
            "google_error": google_error[:120] if google_error else "",
        },
        sort_keys=True,
    )
    if google_error:
        message = google_error_description or google_error
        GMAIL_OAUTH_DIAGNOSTICS["last_google_error"] = message[:500]
        GMAIL_OAUTH_DIAGNOSTICS["last_error"] = f"Google authorization failed: {message[:300]}"
        raise ValueError(f"Google authorization failed: {message}")
    exchange_gmail_code(code, state)


def exchange_gmail_code(code: str, state: str) -> None:
    if not code:
        GMAIL_OAUTH_DIAGNOSTICS["last_error"] = "Missing authorization code."
        GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "missing_code"
        raise ValueError("Missing authorization code.")
    flow = GMAIL_AUTH_FLOWS.pop(state, None)
    if not state or flow is None:
        message = "Authorization state expired or did not match. Start Gmail authorization again from BitBuddy."
        GMAIL_OAUTH_DIAGNOSTICS["last_error"] = message
        GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "state_mismatch"
        raise ValueError(message)
    try:
        created_at = float(flow.get("created_at") or "0")
    except ValueError:
        created_at = 0
    if created_at <= 0 or time.time() - created_at > GMAIL_OAUTH_FLOW_TTL_SECONDS:
        message = "Authorization state expired. Start Gmail authorization again from BitBuddy."
        GMAIL_OAUTH_DIAGNOSTICS["last_error"] = message
        GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "expired_state"
        raise ValueError(message)
    config = load_config().email
    client_secret = get_credentials(config.gmail_credentials_ref).get("client_secret", "")
    if not config.gmail_client_id:
        raise ValueError("Gmail OAuth client ID is not configured.")
    payload_data = {
        "grant_type": "authorization_code",
        "client_id": config.gmail_client_id,
        "code": code,
        "redirect_uri": flow.get("redirect_uri") or gmail_redirect_uri(config),
    }
    if flow.get("mode") == "desktop_pkce":
        payload_data["code_verifier"] = flow["verifier"]
        if client_secret:
            payload_data["client_secret"] = client_secret
    elif client_secret:
        payload_data["client_secret"] = client_secret
    else:
        raise ValueError("Gmail OAuth client secret is required for legacy Web Application OAuth. Switch to Desktop app OAuth or enter a client secret.")
    GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "started"
    payload = urlencode(payload_data).encode("utf-8")
    request = urllib.request.Request(GOOGLE_TOKEN_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        GMAIL_OAUTH_DIAGNOSTICS["last_error"] = f"Gmail token exchange failed: {detail or error}"
        GMAIL_OAUTH_DIAGNOSTICS["last_google_error"] = detail or str(error)
        GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = f"http_error:{error.code}"
        raise ValueError(f"Gmail token exchange failed: {detail or error}") from error
    except (OSError, json.JSONDecodeError) as error:
        GMAIL_OAUTH_DIAGNOSTICS["last_error"] = f"Gmail token exchange failed: {error}"
        GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "error"
        raise ValueError(f"Gmail token exchange failed: {error}") from error
    access_token = str(data.get("access_token") or "")
    refresh_token = str(data.get("refresh_token") or "")
    expires_in = int(data.get("expires_in") or 0)
    if not access_token or not refresh_token:
        message = "Gmail token response did not include access and refresh tokens. Try connecting again and make sure offline access is allowed."
        GMAIL_OAUTH_DIAGNOSTICS["last_error"] = message
        GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "missing_tokens"
        raise ValueError(message)
    GMAIL_OAUTH_DIAGNOSTICS["last_error"] = ""
    GMAIL_OAUTH_DIAGNOSTICS["last_google_error"] = ""
    GMAIL_OAUTH_DIAGNOSTICS["last_token_exchange_status"] = "success"
    GMAIL_OAUTH_DIAGNOSTICS["last_connected_at"] = str(int(time.time()))
    put_credentials(
        config.gmail_token_ref or flow["token_ref"],
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": str(int(time.time()) + max(0, expires_in)),
            "account_id": config.email_address or "Gmail",
        },
    )


def start_codex_callback_server() -> str:
    class CodexCallbackServer(ThreadingHTTPServer):
        allow_reuse_address = True

    class CodexCallbackHandler(BaseHTTPRequestHandler):
        server_version = "BitBuddyCodexOAuth/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            code = (params.get("code") or [""])[0]
            state = (params.get("state") or [""])[0]
            try:
                exchange_codex_code(code, state)
                html = codex_callback_html("Codex connected", "BitBuddy is authorized for Codex. You can close this tab and return to Settings.", ok=True)
                status = HTTPStatus.OK
            except ValueError as error:
                html = codex_callback_html("Codex authorization failed", str(error), ok=False)
                status = HTTPStatus.BAD_REQUEST
            encoded = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            return

    try:
        server = CodexCallbackServer(("localhost", 1455), CodexCallbackHandler)
    except OSError as error:
        return f"Could not start Codex authorization callback on http://localhost:1455/auth/callback: {error}"

    def serve_once() -> None:
        try:
            server.timeout = 300
            server.handle_request()
        finally:
            server.server_close()

    threading.Thread(target=serve_once, daemon=True).start()
    return ""


def codex_oauth_status() -> dict[str, Any]:
    credentials = get_credentials(CODEX_SECRET_REF)
    if credentials.get("access_token") and credentials.get("refresh_token"):
        account = credentials.get("account_id") or "ChatGPT"
        return {"ok": True, "connected": True, "message": f"Connected to Codex as {account}."}
    return {"ok": False, "connected": False, "message": "Codex is not authorized for BitBuddy."}


def exchange_codex_code(code: str, state: str) -> None:
    if not code:
        raise ValueError("Missing authorization code.")
    flow = CODEX_AUTH_FLOWS.pop(state, None)
    if not state or flow is None:
        raise ValueError("Authorization state expired or did not match. Start Codex authorization again from BitBuddy.")
    payload = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CODEX_CLIENT_ID,
            "code": code,
            "code_verifier": flow["verifier"],
            "redirect_uri": CODEX_REDIRECT_URI,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        CODEX_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(f"Token exchange failed: {detail or error}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Token exchange failed: {error}") from error
    access_token = str(data.get("access_token") or "")
    refresh_token = str(data.get("refresh_token") or "")
    expires_in = int(data.get("expires_in") or 0)
    if not access_token or not refresh_token:
        raise ValueError("Token response did not include access and refresh tokens.")
    put_credentials(
        CODEX_SECRET_REF,
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": str(int(time.time()) + max(0, expires_in)),
            "account_id": codex_account_id(access_token) or "ChatGPT",
        },
    )


def parse_codex_authorization_input(value: str) -> tuple[str, str]:
    clean = value.strip()
    if not clean:
        raise ValueError("Paste the callback URL or authorization code from the browser.")
    if clean.startswith("http://") or clean.startswith("https://"):
        params = parse_qs(urlparse(clean).query)
        return (params.get("code") or [""])[0], (params.get("state") or [""])[0]
    if "code=" in clean:
        params = parse_qs(clean.lstrip("?"))
        return (params.get("code") or [""])[0], (params.get("state") or [""])[0]
    if "#" in clean:
        code, state = clean.split("#", 1)
        return code.strip(), state.strip()
    if len(CODEX_AUTH_FLOWS) == 1:
        state = next(iter(CODEX_AUTH_FLOWS.keys()))
        return clean, state
    raise ValueError("Paste the full callback URL so BitBuddy can verify the authorization state.")


def parse_gmail_authorization_input(value: str) -> tuple[str, str]:
    clean = value.strip()
    if not clean:
        raise ValueError("Paste the Gmail callback URL or authorization code from the browser.")
    if clean.startswith("http://") or clean.startswith("https://"):
        params = parse_qs(urlparse(clean).query)
        return (params.get("code") or [""])[0], (params.get("state") or [""])[0]
    if "code=" in clean:
        params = parse_qs(clean.lstrip("?"))
        return (params.get("code") or [""])[0], (params.get("state") or [""])[0]
    if "#" in clean:
        code, state = clean.split("#", 1)
        return code.strip(), state.strip()
    if len(GMAIL_AUTH_FLOWS) == 1:
        state = next(iter(GMAIL_AUTH_FLOWS.keys()))
        return clean, state
    raise ValueError("Paste the full Gmail callback URL so BitBuddy can verify the authorization state.")


def token_urlsafe(length: int) -> str:
    return base64.urlsafe_b64encode(py_secrets.token_bytes(length)).decode("ascii").rstrip("=")


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def codex_account_id(access_token: str) -> str:
    parts = access_token.split(".")
    if len(parts) != 3:
        return ""
    try:
        raw = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return ""
    auth = payload.get("https://api.openai.com/auth") if isinstance(payload, dict) else None
    if isinstance(auth, dict):
        return str(auth.get("chatgpt_account_id") or auth.get("user_id") or "")
    return ""


def codex_callback_html(title: str, message: str, *, ok: bool) -> str:
    color = "#6ee7b7" if ok else "#f87171"
    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><title>{title}</title></head>
<body style=\"margin:0;background:#0b1120;color:#eef5ff;font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh\">
<main style=\"max-width:34rem;padding:2rem;border:1px solid #263449;border-radius:1rem;background:#111827\">
<h1 style=\"margin-top:0;color:{color}\">{title}</h1>
<p style=\"line-height:1.5;color:#b8c7dc\">{message}</p>
</main></body></html>"""


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
        with db_connection(GLOBAL_DB_PATH, row_factory=sqlite3.Row) as conn:
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
