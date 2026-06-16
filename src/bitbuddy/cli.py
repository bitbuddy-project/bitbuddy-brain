from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .activity import list_activity, log_activity
from .auth import API_TOKEN_HEADER, api_token_path, get_api_token, is_loopback_host, rotate_api_token
from .chats.repository import delete_chat, get_chat, list_recent_chats
from .config import ProviderConfig, load_config, update_calendar_config, update_email_config, update_mcp_config, update_model_runtime_config, upsert_mcp_server, validate_timezone, write_config
from .database import db_connection
from .personality import BUILTIN_PERSONALITIES
from .paths import APP_DIR, CONFIG_PATH, GLOBAL_DB_PATH, PERSONALITIES_DIR, WEB_DIR, ensure_app_dirs
from .librarian import (
    delete_card,
    format_whisper,
    get_card,
    get_relevant_whisper,
    index_all_projects,
    list_cards,
    regenerate_card,
)
from .managed_tools import computer_use_linux_status, install_computer_use_linux, resolve_managed_command
from .memory.project import index_project, list_projects, project_map, register_project
from .providers import ProviderClient
from .server import serve
from .self_model import record_personality_quirks


SERVICE_NAME = "bitbuddy.service"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        print(error, file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bitbuddy",
        description="Your local companion that learns, grows with you, and is built for fully autonomous workflows.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    setup_parser = subparsers.add_parser("setup", help="Initialize BitBuddy config, personality, and memories.")
    setup_parser.set_defaults(handler=run_setup)

    serve_parser = subparsers.add_parser("serve", help="Run the BitBuddy backend server.")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host for the backend server.")
    serve_parser.add_argument("--port", type=int, default=8787, help="Port for the backend server.")
    serve_parser.add_argument("--allow-lan", action="store_true", help="Allow binding the backend to a non-loopback/LAN interface. Requires local API token auth.")
    serve_parser.set_defaults(handler=run_serve)

    web_parser = subparsers.add_parser("web", help="Run the SvelteKit/Vite web app.")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host for the dev server.")
    web_parser.add_argument("--port", default="5173", help="Port for the dev server.")
    web_parser.set_defaults(handler=run_web)

    dashboard_parser = subparsers.add_parser("dashboard", help="Start the local web UI dashboard.")
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="Host for the dev server.")
    dashboard_parser.add_argument("--port", default="5173", help="Port for the dev server.")
    dashboard_parser.add_argument("--api-host", default="127.0.0.1", help="Host for the backend server.")
    dashboard_parser.add_argument("--api-port", type=int, default=8787, help="Port for the backend server.")
    dashboard_parser.add_argument("--allow-lan", action="store_true", help="Allow binding the backend to a non-loopback/LAN interface. Requires local API token auth.")
    dashboard_parser.add_argument("--no-open", action="store_true", help="Do not open the dashboard in a browser.")
    dashboard_parser.set_defaults(handler=run_dashboard)

    service_parser = subparsers.add_parser("service", help="Install and control the BitBuddy user systemd service.")
    service_subparsers = service_parser.add_subparsers(dest="service_command", metavar="command")
    service_install = service_subparsers.add_parser("install", help="Write the user systemd service file.")
    service_install.set_defaults(handler=service_install_command)
    service_enable = service_subparsers.add_parser("enable", help="Enable and start the user systemd service.")
    service_enable.set_defaults(handler=service_enable_command)
    service_disable = service_subparsers.add_parser("disable", help="Disable and stop the user systemd service.")
    service_disable.set_defaults(handler=service_disable_command)
    for name, help_text in (
        ("start", "Start the user systemd service."),
        ("stop", "Stop the user systemd service."),
        ("restart", "Restart the user systemd service."),
        ("status", "Show service status."),
    ):
        service_action = service_subparsers.add_parser(name, help=help_text)
        service_action.set_defaults(handler=service_action_command)
    service_logs = service_subparsers.add_parser("logs", help="Show service logs from journalctl.")
    service_logs.add_argument("-n", "--lines", type=int, default=100, help="Number of log lines to show.")
    service_logs.add_argument("-f", "--follow", action="store_true", help="Follow new log lines.")
    service_logs.set_defaults(handler=service_logs_command)
    service_parser.set_defaults(handler=service_status_command)

    doctor_parser = subparsers.add_parser("doctor", help="Diagnose BitBuddy setup, storage, services, autonomy, and web search.")
    doctor_subparsers = doctor_parser.add_subparsers(dest="doctor_command", metavar="command")
    doctor_fix = doctor_subparsers.add_parser("fix", help="Apply safe automatic repairs suggested by doctor.")
    doctor_fix.set_defaults(handler=doctor_fix_command)
    doctor_parser.set_defaults(handler=doctor_command)

    status_parser = subparsers.add_parser("status", help="Show local BitBuddy setup and component status.")
    status_parser.add_argument("--doctor", action="store_true", help="Include doctor pass/warn/fail totals.")
    status_parser.set_defaults(handler=status_command)

    config_parser = subparsers.add_parser("config", help="View or edit local configuration.")
    config_subparsers = config_parser.add_subparsers(dest="config_command", metavar="command")
    config_show = config_subparsers.add_parser("show", help="Print config.yaml.")
    config_show.set_defaults(handler=config_show_command)
    config_path = config_subparsers.add_parser("path", help="Print the config path.")
    config_path.set_defaults(handler=config_path_command)
    config_edit = config_subparsers.add_parser("edit", help="Open config.yaml in $EDITOR.")
    config_edit.set_defaults(handler=config_edit_command)
    config_gmail_full = config_subparsers.add_parser("gmail-full-access", help="Enable or disable Gmail full mail scope for permanent delete/empty Trash.")
    config_gmail_group = config_gmail_full.add_mutually_exclusive_group(required=True)
    config_gmail_group.add_argument("--enable", action="store_true", help="Request https://mail.google.com/ on the next Gmail reconnect.")
    config_gmail_group.add_argument("--disable", action="store_true", help="Use the safer Gmail modify scope on the next Gmail reconnect.")
    config_gmail_full.set_defaults(handler=config_gmail_full_access_command)
    config_parser.set_defaults(handler=config_show_command)

    model_parser = subparsers.add_parser("model", help="List, add, or switch model providers.")
    model_parser.add_argument("--list", action="store_true", help="List configured providers.")
    model_parser.add_argument("--set", dest="set_provider", help="Set active provider by key/type.")
    model_parser.add_argument("--add", action="store_true", help="Open the provider add/update picker.")
    model_parser.set_defaults(handler=model_command)

    logs_parser = subparsers.add_parser("logs", help="View local BitBuddy activity logs.")
    logs_parser.add_argument("kind", nargs="?", default="all", choices=["all", "errors"], help="Log stream to show.")
    logs_parser.add_argument("-n", "--limit", type=int, default=50, help="Number of rows to show.")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow new activity rows.")
    logs_parser.add_argument("--json", action="store_true", help="Print JSON rows.")
    logs_parser.set_defaults(handler=logs_command)

    sessions_parser = subparsers.add_parser("sessions", help="Manage persisted chat sessions.")
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command", metavar="command")
    sessions_list = sessions_subparsers.add_parser("list", help="List recent sessions.")
    sessions_list.add_argument("-n", "--limit", type=int, default=20, help="Number of sessions to list.")
    sessions_list.add_argument("--search", default="", help="Search session titles.")
    sessions_list.set_defaults(handler=sessions_list_command)
    sessions_show = sessions_subparsers.add_parser("show", help="Show a session transcript.")
    sessions_show.add_argument("session", help="Session id.")
    sessions_show.set_defaults(handler=sessions_show_command)
    sessions_export = sessions_subparsers.add_parser("export", help="Export a session as JSON.")
    sessions_export.add_argument("session", help="Session id.")
    sessions_export.add_argument("output", nargs="?", help="Output path. Defaults to stdout.")
    sessions_export.set_defaults(handler=sessions_export_command)
    sessions_rename = sessions_subparsers.add_parser("rename", help="Rename a session.")
    sessions_rename.add_argument("session", help="Session id.")
    sessions_rename.add_argument("title", help="New session title.")
    sessions_rename.set_defaults(handler=sessions_rename_command)
    sessions_delete = sessions_subparsers.add_parser("delete", help="Delete a session after preserving its continuity capsule.")
    sessions_delete.add_argument("session", help="Session id.")
    sessions_delete.add_argument("--yes", action="store_true", help="Confirm deletion.")
    sessions_delete.set_defaults(handler=sessions_delete_command)
    sessions_prune = sessions_subparsers.add_parser("prune", help="Delete old sessions, keeping the newest N.")
    sessions_prune.add_argument("--keep", type=int, default=50, help="Number of newest sessions to keep.")
    sessions_prune.add_argument("--yes", action="store_true", help="Confirm pruning.")
    sessions_prune.set_defaults(handler=sessions_prune_command)
    sessions_parser.set_defaults(handler=sessions_list_command)

    backup_parser = subparsers.add_parser("backup", help="Back up the local BitBuddy home directory.")
    backup_parser.add_argument("output", nargs="?", help="Output zip path. Defaults to ./bitbuddy-backup-<timestamp>.zip")
    backup_parser.add_argument("--include-secrets", action="store_true", help="Include secrets.json in the backup zip.")
    backup_parser.set_defaults(handler=backup_command)

    update_parser = subparsers.add_parser("update", help="Update a source-installed BitBuddy checkout.")
    update_parser.add_argument("--branch", default="stable", help="Git branch to update from. Defaults to stable.")
    update_parser.add_argument("--no-autostash", action="store_true", help="Refuse local changes instead of stashing and restoring them.")
    update_parser.add_argument("--skip-doctor", action="store_true", help="Do not run bitbuddy doctor after updating.")
    update_parser.set_defaults(handler=update_command)

    completion_parser = subparsers.add_parser("completion", help="Print a shell completion script.")
    completion_parser.add_argument("shell", choices=["bash", "zsh", "fish"], help="Shell to generate completion for.")
    completion_parser.set_defaults(handler=completion_command)

    provider_parser = subparsers.add_parser("provider", help="Inspect the configured local model provider.")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_command", metavar="command")

    provider_check = provider_subparsers.add_parser("check", help="Check Ollama or llama.cpp connectivity.")
    provider_check.set_defaults(handler=provider_check_command)

    provider_models = provider_subparsers.add_parser("models", help="List models from the configured provider.")
    provider_models.set_defaults(handler=provider_models_command)

    provider_test = provider_subparsers.add_parser("stream-test", help="Run a short diagnostic stream and split thinking output.")
    provider_test.add_argument("--prompt", default="Reply with one short sentence.", help="Prompt for the diagnostic call.")
    provider_test.set_defaults(handler=provider_stream_test_command)

    provider_parser.set_defaults(handler=provider_help)

    mcp_parser = subparsers.add_parser("mcp", help="Manage MCP tool servers.")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", metavar="command")

    mcp_list = mcp_subparsers.add_parser("list", help="List configured MCP servers.")
    mcp_list.set_defaults(handler=mcp_list_command)

    mcp_install_computer = mcp_subparsers.add_parser("install-computer-use-linux", help="Install BitBuddy's managed Linux desktop-control MCP binary.")
    mcp_install_computer.set_defaults(handler=mcp_install_computer_use_linux_command)

    mcp_doctor_computer = mcp_subparsers.add_parser("doctor-computer-use-linux", help="Run computer-use-linux doctor using BitBuddy's managed binary.")
    mcp_doctor_computer.set_defaults(handler=mcp_doctor_computer_use_linux_command)

    mcp_add_computer = mcp_subparsers.add_parser("add-computer-use-linux", help="Configure the Linux desktop-control MCP server.")
    mcp_add_computer.add_argument("--command", default="managed:computer-use-linux", help="Path or command for computer-use-linux.")
    mcp_add_computer.add_argument("--no-install", action="store_true", help="Only write config; do not install the managed binary.")
    mcp_add_computer.set_defaults(handler=mcp_add_computer_use_linux_command)

    mcp_parser.set_defaults(handler=mcp_help)

    projects_parser = subparsers.add_parser("projects", help="Manage read-only project memories.")
    project_subparsers = projects_parser.add_subparsers(dest="project_command", metavar="command")

    add_project_parser = project_subparsers.add_parser("add", help="Register read-only project paths.")
    add_project_parser.add_argument("name", help="Human-readable project name.")
    add_project_parser.add_argument("paths", nargs="+", help="Project directories or files to track read-only.")
    add_project_parser.set_defaults(handler=add_project_command)

    list_projects_parser = project_subparsers.add_parser("list", help="List registered projects.")
    list_projects_parser.set_defaults(handler=list_projects_command)

    index_project_parser = project_subparsers.add_parser("index", help="Scan a project and update its SQLite memory.")
    index_project_parser.add_argument("project", help="Project id or name.")
    index_project_parser.set_defaults(handler=index_project_command)

    map_project_parser = project_subparsers.add_parser("map", help="Print the compact project memory map.")
    map_project_parser.add_argument("project", help="Project id or name.")
    map_project_parser.add_argument("--limit", type=int, default=200, help="Maximum files to include.")
    map_project_parser.set_defaults(handler=project_map_command)

    projects_parser.set_defaults(handler=projects_help)

    # Librarian / context whisper commands
    librarian_parser = subparsers.add_parser("librarian", help="Manage the context whisper (librarian) system.")
    librarian_subparsers = librarian_parser.add_subparsers(dest="librarian_command", metavar="command")

    lib_add = librarian_subparsers.add_parser("add", help="Build a librarian card from an indexed project's memory.")
    lib_add.add_argument("project", help="Project id or name.")
    lib_add.set_defaults(handler=librarian_add_command)

    lib_list = librarian_subparsers.add_parser("list", help="List all librarian cards.")
    lib_list.set_defaults(handler=librarian_list_command)

    lib_show = librarian_subparsers.add_parser("show", help="Show a librarian card's contents.")
    lib_show.add_argument("project", help="Project id or name.")
    lib_show.set_defaults(handler=librarian_show_command)

    lib_reset = librarian_subparsers.add_parser("reset", help="Regenerate a librarian card from project memory.")
    lib_reset.add_argument("project", help="Project id or name.")
    lib_reset.set_defaults(handler=librarian_reset_command)

    lib_index_all = librarian_subparsers.add_parser("index-all", help="Rebuild librarian cards for all registered projects.")
    lib_index_all.set_defaults(handler=librarian_index_all_command)

    lib_test = librarian_subparsers.add_parser("test-whisper", help="Show what whisper a query would produce.")
    lib_test.add_argument("query", help="Test query string.", nargs="?")
    lib_test.set_defaults(handler=librarian_test_whisper_command)

    # Auth / local API token
    auth_parser = subparsers.add_parser("auth", help="Manage the local API token used to authorize the web UI and LAN access.")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", metavar="command")

    auth_token = auth_subparsers.add_parser("token", help="Print the local API token (creating one if needed).")
    auth_token.set_defaults(handler=auth_token_command)

    auth_rotate = auth_subparsers.add_parser("rotate", help="Generate a new local API token, invalidating the old one.")
    auth_rotate.set_defaults(handler=auth_rotate_command)

    auth_parser.set_defaults(handler=auth_token_command)

    return parser


def auth_token_command(_args: argparse.Namespace) -> int:
    token = get_api_token()
    print(token)
    print(f"Stored at: {api_token_path()}", file=sys.stderr)
    print(f"Send it as the {API_TOKEN_HEADER} header (used by the web UI and required for LAN access).", file=sys.stderr)
    return 0


def auth_rotate_command(_args: argparse.Namespace) -> int:
    token = rotate_api_token()
    print(token)
    print("Rotated the local API token. Existing browser sessions and LAN clients must use the new token.", file=sys.stderr)
    return 0


def run_setup(_args: argparse.Namespace) -> int:
    try:
        import questionary
        from questionary import Style
    except ImportError:
        print("questionary is required for setup. Install this package with `pip install -e .` first.", file=sys.stderr)
        return 1

    style = Style(
        [
            ("qmark", "fg:#79b8ff bold"),
            ("question", "fg:#eef5ff bold"),
            ("answer", "fg:#6ee7b7 bold"),
            ("pointer", "fg:#79b8ff bold"),
            ("highlighted", "fg:#eef5ff noreverse noinherit"),
            ("selected", "fg:#eef5ff noreverse noinherit"),
            ("separator", "fg:#6f839e"),
            ("instruction", "fg:#9fb2ca"),
            ("text", "fg:#eef5ff"),
            ("disabled", "fg:#6f839e italic"),
        ]
    )

    print()
    print("BitBuddy setup")
    print("Your local companion that learns, grows with you, and keeps its memory close to home.")
    print()

    current_config = load_config() if CONFIG_PATH.exists() else None
    setup_action = "Start new setup"
    if current_config is not None:
        setup_action = questionary.select(
            "Existing BitBuddy setup found. What do you want to do?",
            choices=["Quick: calendar/reminder settings", "Quick: service/autostart settings", "Full guided setup", "Keep current setup", "Start new setup"],
            default="Quick: calendar/reminder settings",
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if setup_action is None:
            return 1
        if setup_action == "Quick: calendar/reminder settings":
            if not configure_calendar_setup(questionary, style, current_config):
                return 1
            return 0
        if setup_action == "Quick: service/autostart settings":
            return 0 if configure_service_setup(questionary, style) else 1
        if setup_action == "Keep current setup":
            print(f"Keeping current setup at {CONFIG_PATH}")
            print("Run `bitbuddy serve` when you are ready.")
            return 0
        if setup_action == "Full guided setup":
            setup_action = "Modify current setup"

    provider_default = "Ollama"
    provider_url_default = "http://127.0.0.1:11434"
    provider_model_default = ""
    scan_interval_default = 60
    buddy_name_default = "BitBuddy"
    presentation_default = "genderless"
    pronouns_default = "they/them"
    personality_id_default = "cozy-companion"
    expressiveness_default = "balanced"
    proactivity_default = "helpful_nudges"
    bitbuddy_likes_default: list[str] = []
    bitbuddy_dislikes_default: list[str] = []
    location_label_default = ""
    timezone_default = "UTC"
    locale_default = "en-US"
    max_tool_rounds_default = 99
    configure_profile = True
    configure_context = True
    configure_chat = True
    configure_provider = True
    configure_scan_interval = True
    configure_project_memory: bool | None = None
    configure_calendar: bool | None = None
    configure_service: bool | None = None
    if setup_action == "Modify current setup" and current_config is not None:
        buddy_name_default = current_config.name
        presentation_default = current_config.presentation.style
        pronouns_default = current_config.presentation.pronouns
        personality_id_default = current_config.personality.id
        expressiveness_default = current_config.personality.expressiveness
        proactivity_default = current_config.personality.proactivity
        bitbuddy_likes_default = list(current_config.personality.bitbuddy_likes)
        bitbuddy_dislikes_default = list(current_config.personality.bitbuddy_dislikes)
        location_label_default = current_config.user_context.location_label
        timezone_default = current_config.user_context.timezone
        locale_default = current_config.user_context.locale
        max_tool_rounds_default = current_config.chat.max_tool_rounds
        provider_default = provider_label_from_key(current_config.provider.type)
        provider_url_default = current_config.provider.url or provider_url_default_for(current_config.provider.type)
        provider_model_default = current_config.provider.model
        scan_interval_default = current_config.project_scan_interval_seconds
        optional_sections = questionary.checkbox(
            "Which setup sections do you want to revise now? Unchecked sections stay unchanged.",
            choices=[
                questionary.Choice("Profile and personality", checked=False),
                questionary.Choice("Local context", checked=False),
                questionary.Choice("Chat tool budget", checked=False),
                questionary.Choice("Local model provider", checked=False),
                questionary.Choice("Project scan interval", checked=False),
                questionary.Choice("Read-only project memory", checked=False),
                questionary.Choice("Calendar reminders", checked=False),
                questionary.Choice("Service/autostart", checked=False),
            ],
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if optional_sections is None:
            return 1
        configure_profile = "Profile and personality" in optional_sections
        configure_context = "Local context" in optional_sections
        configure_chat = "Chat tool budget" in optional_sections
        configure_provider = "Local model provider" in optional_sections
        configure_scan_interval = "Project scan interval" in optional_sections
        configure_project_memory = "Read-only project memory" in optional_sections
        configure_calendar = "Calendar reminders" in optional_sections
        configure_service = "Service/autostart" in optional_sections

    buddy_name = buddy_name_default
    presentation_style = presentation_default
    pronouns = pronouns_default
    personality_id = personality_id_default
    expressiveness = expressiveness_default
    proactivity = proactivity_default
    bitbuddy_likes = bitbuddy_likes_default
    bitbuddy_dislikes = bitbuddy_dislikes_default
    if configure_profile:
        buddy_name = (
            questionary.text(
                "What do you want to name your BitBuddy?",
                default=buddy_name_default,
                qmark="◆",
                style=style,
            ).ask()
            or buddy_name_default
        )

        presentation_style = questionary.select(
            "How should I present myself?",
            choices=["female", "male", "genderless"],
            default=presentation_default,
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if presentation_style is None:
            return 1

        default_pronouns = {
            "female": "she/her",
            "male": "he/him",
            "genderless": "they/them",
        }.get(presentation_style, "they/them")
        pronouns = pronouns_default if presentation_style == presentation_default else default_pronouns

        personality_choices = [
            f"{raw['display_name']} ({personality_id})"
            for personality_id, raw in BUILTIN_PERSONALITIES.items()
        ]
        personality_default = next(
            (
                choice
                for choice in personality_choices
                if choice.endswith(f"({personality_id_default})")
            ),
            personality_choices[0],
        )
        personality_label = questionary.select(
            "What kind of companion should I be?",
            choices=personality_choices,
            default=personality_default,
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if personality_label is None:
            return 1
        personality_id = personality_label.rsplit("(", 1)[-1].rstrip(")")

        expressiveness = questionary.select(
            "How expressive should this personality be?",
            choices=["subtle", "balanced", "expressive"],
            default=expressiveness_default,
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if expressiveness is None:
            return 1

        proactivity_label = questionary.select(
            "How proactive should I be?",
            choices=["quiet", "helpful nudges", "active coworker"],
            default={
                "quiet": "quiet",
                "helpful_nudges": "helpful nudges",
                "active_coworker": "active coworker",
            }.get(proactivity_default, "helpful nudges"),
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if proactivity_label is None:
            return 1
        proactivity = proactivity_label.replace(" ", "_")

        bitbuddy_likes = parse_setup_quirks(
            questionary.text(
                "Optional: up to 3 things BitBuddy likes (comma-separated)",
                default=", ".join(bitbuddy_likes_default),
                qmark="◆",
                style=style,
            ).ask()
            or ""
        )
        bitbuddy_dislikes = parse_setup_quirks(
            questionary.text(
                "Optional: up to 3 things BitBuddy dislikes (comma-separated)",
                default=", ".join(bitbuddy_dislikes_default),
                qmark="◆",
                style=style,
            ).ask()
            or ""
        )

    location_label = location_label_default
    timezone = timezone_default
    locale = locale_default
    if configure_context:
        location_label = (
            questionary.text(
                "Where are you based? (optional city/region label)",
                default=location_label_default,
                qmark="◆",
                style=style,
            ).ask()
            or location_label_default
        )
        timezone = (
            questionary.text(
                "Your IANA timezone",
                default=timezone_default,
                qmark="◆",
                style=style,
            ).ask()
            or timezone_default
        ).strip()
        validate_timezone(timezone)
        locale = (
            questionary.text(
                "Your locale",
                default=locale_default,
                qmark="◆",
                style=style,
            ).ask()
            or locale_default
        )

    max_tool_rounds = max_tool_rounds_default
    if configure_chat:
        max_tool_rounds_answer = questionary.text(
            "Max tool calls per chat turn",
            default=str(max_tool_rounds_default),
            qmark="◆",
            style=style,
        ).ask()
        max_tool_rounds = parse_tool_round_limit(max_tool_rounds_answer or str(max_tool_rounds_default))

    provider_config = existing_or_empty_provider_config(current_config)
    configured_providers = provider_entries_from_config(current_config)
    active_provider = provider_config.key or provider_config.type
    provider = provider_config.type
    provider_url = provider_config.url
    provider_model = provider_config.model
    if configure_provider:
        configured_providers = [] if setup_action == "Start new setup" else configured_providers
        while True:
            provider_label = questionary.select(
                "Add a model provider",
                choices=["Ollama", "llama.cpp", "OpenAI API", "Codex", "Anthropic", "Done"],
                default=provider_default,
                qmark="◆",
                pointer="›",
                style=style,
            ).ask()
            if provider_label is None:
                return 1
            if provider_label == "Done":
                break
            entry = configure_provider_entry(questionary, style, provider_label, configured_providers)
            configured_providers = [existing for existing in configured_providers if existing.get("type") != entry.get("type")]
            configured_providers.append(entry)
            add_another = questionary.confirm("Add another provider?", default=False, qmark="◆", style=style).ask()
            if not add_another:
                break
        if configured_providers:
            active_label = questionary.select(
                "Which provider should be active now?",
                choices=[provider_choice_label(entry) for entry in configured_providers],
                default=provider_choice_label(configured_providers[0]),
                qmark="◆",
                pointer="›",
                style=style,
            ).ask()
            if active_label is None:
                return 1
            active_provider = provider_type_from_choice_label(active_label)
            active_entry = next((entry for entry in configured_providers if entry.get("type") == active_provider), configured_providers[0])
            provider = str(active_entry.get("type") or "none")
            provider_url = str(active_entry.get("url") or "")
            provider_model = str(active_entry.get("model") or "")
        else:
            active_provider = "none"
            provider = "none"
            provider_url = ""
            provider_model = ""

    scan_interval = scan_interval_default
    if configure_scan_interval:
        scan_interval_answer = questionary.text(
            "Project memory scan interval in seconds (0 disables monitor)",
            default=str(scan_interval_default),
            qmark="◆",
            style=style,
        ).ask()
        scan_interval = parse_scan_interval(scan_interval_answer or str(scan_interval_default))

    ensure_app_dirs()
    presentation_config = {"style": presentation_style, "pronouns": pronouns}
    personality_config = {
        "source": "builtin",
        "id": personality_id,
        "path": None,
        "expressiveness": expressiveness,
        "proactivity": proactivity,
        "quirk_frequency": "occasional",
        "bitbuddy_likes": bitbuddy_likes,
        "bitbuddy_dislikes": bitbuddy_dislikes,
    }
    user_context_config = {
        "location_label": location_label,
        "timezone": timezone,
        "locale": locale,
    }
    chat_config = {
        "max_tool_rounds": max_tool_rounds,
    }
    should_write_core_config = setup_action != "Modify current setup" or any(
        [configure_profile, configure_context, configure_chat, configure_provider, configure_scan_interval]
    )
    if should_write_core_config:
        write_config(
            provider,
            provider_url,
            provider_model,
            scan_interval,
            buddy_name,
            presentation_config,
            personality_config,
            user_context_config,
            chat_config,
            preserve_existing=setup_action == "Modify current setup",
            update_provider=setup_action != "Modify current setup" or configure_provider,
            update_project_scan_interval=setup_action != "Modify current setup" or configure_scan_interval,
        )
        if configure_profile:
            record_personality_quirks(personality_id, bitbuddy_likes, bitbuddy_dislikes)
        if configure_provider or configure_scan_interval:
            update_model_runtime_config(
                {
                    "providers": configured_providers,
                    "active_provider": active_provider,
                    "project_scan_interval_seconds": scan_interval,
                }
            )

        print()
        print(f"Config written: {CONFIG_PATH}")
        print(f"Personality files available: {PERSONALITIES_DIR}")
        log_activity(
            "setup.completed",
            "BitBuddy setup completed",
            {
                "name": buddy_name,
                "provider": provider,
                "model": provider_model,
                "scan_interval_seconds": scan_interval,
                "presentation_style": presentation_style,
                "personality_id": personality_id,
                "expressiveness": expressiveness,
                "proactivity": proactivity,
                "location_label": location_label,
                "timezone": timezone,
                "locale": locale,
                "max_tool_rounds": max_tool_rounds,
            },
        )
    else:
        print()
        print(f"Core config unchanged: {CONFIG_PATH}")

    if provider != "none":
        ok, message = ProviderClient(load_config().provider).health()
        print(message)
        if not ok:
            print("You can still continue and start the provider later.")

    add_memory = configure_project_memory
    if add_memory is None:
        add_memory = questionary.confirm(
            "Add a read-only project memory now?",
            default=False,
            qmark="◆",
            style=style,
        ).ask()
    if add_memory:
        name = questionary.text("Project memory name", qmark="◆", style=style).ask()
        path = questionary.text("Project directory or file", qmark="◆", style=style).ask()
        if name and path:
            project = register_project(name, [path])
            result = index_project(project.id)
            print(
                f"Indexed {result.project.name}: scanned={result.scanned}, changed={result.changed}, "
                f"deleted={result.deleted}, skipped={result.skipped}"
            )

    if configure_calendar is None:
        configure_calendar = bool(
            questionary.confirm(
                "Set up calendar reminders now?",
                default=False,
                qmark="◆",
                style=style,
            ).ask()
        )
    if configure_calendar and not configure_calendar_setup(questionary, style, load_config()):
        return 1

    handle_setup_launch_prompt(questionary, style, configure_service)

    print()
    print("Setup complete.")
    print("Use `bitbuddy serve` for the backend and `bitbuddy dashboard` for the web UI.")
    return 0


def provider_url_question(provider: str) -> str:
    if provider == "llama.cpp":
        return "llama.cpp server address"
    if provider == "ollama":
        return "Ollama server address"
    return "Provider URL"


def provider_type_from_label(label: str) -> str:
    if label == "Ollama":
        return "ollama"
    if label == "llama.cpp":
        return "llama.cpp"
    if label in {"OpenAI", "OpenAI API"}:
        return "openai"
    if label == "Codex":
        return "codex"
    if label == "Anthropic":
        return "anthropic"
    return "none"


def provider_display_name(provider_type: str) -> str:
    if provider_type == "ollama":
        return "Ollama"
    if provider_type == "llama.cpp":
        return "llama.cpp"
    if provider_type == "openai":
        return "OpenAI API"
    if provider_type == "codex":
        return "Codex"
    if provider_type == "anthropic":
        return "Anthropic"
    return "None"


def provider_entries_from_config(config: object | None) -> list[dict[str, Any]]:
    providers = getattr(config, "providers", ()) if config is not None else ()
    entries: list[dict[str, Any]] = []
    for provider in providers:
        if isinstance(provider, ProviderConfig) and provider.type != "none":
            entry = {
                "type": provider.type,
                "url": provider.url,
                "model": provider.model,
                "key": provider.key or provider.type,
                "embedding_model": provider.embedding_model,
                "embedding_url": provider.embedding_url,
                "native_tools": provider.native_tools,
                "has_api_key": provider.has_api_key,
            }
            if provider.api_key_ref:
                entry["api_key_ref"] = provider.api_key_ref
            entries.append(entry)
    if not entries:
        provider = existing_or_empty_provider_config(config)
        if provider.type != "none":
            entry = {"type": provider.type, "url": provider.url, "model": provider.model, "key": provider.key or provider.type, "has_api_key": provider.has_api_key}
            if provider.api_key_ref:
                entry["api_key_ref"] = provider.api_key_ref
            entries.append(entry)
    return entries


def provider_choice_label(entry: dict[str, Any]) -> str:
    provider_type = str(entry.get("type") or "none")
    model = str(entry.get("model") or "").strip()
    return f"{provider_display_name(provider_type)}{f' · {model}' if model else ''}"


def provider_type_from_choice_label(label: str) -> str:
    return provider_type_from_label(label.split(" · ", 1)[0])


def configure_provider_entry(questionary: Any, style: Any, provider_label: str, existing: list[dict[str, Any]]) -> dict[str, Any]:
    provider_type = provider_type_from_label(provider_label)
    previous = next((entry for entry in existing if entry.get("type") == provider_type), {})
    if provider_type == "codex":
        provider_url = provider_url_default_for(provider_type)
    else:
        default_url = str(previous.get("url") or provider_url_default_for(provider_type))
        provider_url = questionary.text(provider_url_question(provider_type), default=default_url, qmark="◆", style=style).ask() or default_url
    detected_models = detect_provider_models(provider_type, provider_url) if provider_type not in {"openai", "codex", "anthropic"} else []
    default_model = str(previous.get("model") or (detected_models[0] if detected_models else provider_model_default_for(provider_type)))
    if detected_models:
        print(f"Found model: {default_model}")
    provider_model = questionary.text("Model name", default=default_model, qmark="◆", style=style).ask() or default_model
    entry: dict[str, Any] = {"type": provider_type, "url": provider_url, "model": provider_model}
    if provider_type in {"openai", "anthropic"}:
        has_key = bool(previous.get("has_api_key"))
        prompt = "API key" + (" (leave blank to keep existing)" if has_key else "")
        api_key = questionary.password(prompt, qmark="◆", style=style).ask() or ""
        if api_key:
            entry["api_key"] = api_key
        elif has_key:
            entry["has_api_key"] = True
    elif provider_type == "codex":
        print("Codex uses ChatGPT login. Finish login from Settings or run `codex login --device-auth`.")
    return entry


def provider_label_from_key(provider: str) -> str:
    if provider == "ollama":
        return "Ollama"
    if provider == "llama.cpp":
        return "llama.cpp"
    if provider == "openai":
        return "OpenAI API"
    if provider == "codex":
        return "Codex"
    if provider == "anthropic":
        return "Anthropic"
    return "Skip for now"


def existing_or_empty_provider_config(config: object | None) -> ProviderConfig:
    provider = getattr(config, "provider", None)
    if isinstance(provider, ProviderConfig):
        return provider
    return ProviderConfig(type="none", url="", model="")


def current_provider_key(config: object | None) -> str:
    return existing_or_empty_provider_config(config).type


def provider_config_from_setup_choice(provider_label: str, setup_action: str, current_config: object | None) -> tuple[ProviderConfig, bool]:
    existing = existing_or_empty_provider_config(current_config)
    if provider_label == "Skip for now":
        if setup_action == "Modify current setup" and existing.type != "none":
            return existing, True
        return ProviderConfig(type="none", url="", model=""), False
    return ProviderConfig(type=provider_label.lower(), url="", model=""), False


def provider_url_default_for(provider: str) -> str:
    if provider == "ollama":
        return "http://127.0.0.1:11434"
    if provider == "llama.cpp":
        return "http://127.0.0.1:8080"
    if provider == "openai":
        return "https://api.openai.com"
    if provider == "codex":
        return "codex://chatgpt"
    if provider == "anthropic":
        return "https://api.anthropic.com"
    return ""


def provider_model_default_for(provider: str) -> str:
    if provider == "openai":
        return "gpt-5.5"
    if provider == "codex":
        return "gpt-5.5"
    if provider == "anthropic":
        return "claude-opus-4-8"
    return ""


def detect_provider_models(provider: str, provider_url: str) -> list[str]:
    client = ProviderClient(ProviderConfig(type=provider, url=provider_url, model=""))
    try:
        return client.models()
    except (OSError, ValueError):
        return []


def parse_scan_interval(value: str) -> int:
    try:
        interval = int(value)
    except ValueError as error:
        raise ValueError("Project memory scan interval must be a whole number of seconds.") from error
    if interval < 0:
        raise ValueError("Project memory scan interval cannot be negative.")
    return interval


def parse_tool_round_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise ValueError("Max tool calls per chat turn must be a whole number.") from error
    if limit < 1:
        raise ValueError("Max tool calls per chat turn must be at least 1.")
    return limit


def configure_calendar_setup(questionary: Any, style: Any, current_config: object | None = None) -> bool:
    calendar = getattr(current_config, "calendar", None)
    enabled_default = bool(getattr(calendar, "enabled", False))
    enabled = questionary.confirm(
        "Enable calendar reminders and schedule awareness?",
        default=enabled_default,
        qmark="◆",
        style=style,
    ).ask()
    if enabled is None:
        return False

    if not enabled:
        update_calendar_config({"enabled": False})
        print("Calendar setup updated: calendar is off.")
        return True

    upcoming_default = max(1, int(getattr(calendar, "reminder_upcoming_minutes", 60) or 60))
    soon_default = max(1, int(getattr(calendar, "reminder_starting_soon_minutes", 15) or 15))
    upcoming = setup_positive_int(
        questionary,
        style,
        "Upcoming reminder lead time in minutes",
        upcoming_default,
    )
    if upcoming is None:
        return False
    starting_soon = setup_positive_int(
        questionary,
        style,
        "Starting-soon reminder lead time in minutes",
        soon_default,
    )
    if starting_soon is None:
        return False

    urgent_interrupts = questionary.confirm(
        "Show urgent UI alerts for starting-soon reminders?",
        default=bool(getattr(calendar, "urgent_interrupts_enabled", True)),
        qmark="◆",
        style=style,
    ).ask()
    if urgent_interrupts is None:
        return False
    persistent_urgent = False
    if urgent_interrupts:
        persistent_answer = questionary.confirm(
            "Keep urgent reminders visible until dismissed or opened?",
            default=bool(getattr(calendar, "urgent_interrupt_persistent", True)),
            qmark="◆",
            style=style,
        ).ask()
        if persistent_answer is None:
            return False
        persistent_urgent = bool(persistent_answer)

    conflict_warnings = questionary.confirm(
        "Warn when calendar events overlap?",
        default=bool(getattr(calendar, "conflict_warnings_enabled", True)),
        qmark="◆",
        style=style,
    ).ask()
    if conflict_warnings is None:
        return False
    chat_nudges = questionary.confirm(
        "Post calendar reminders directly into chat too?",
        default=bool(getattr(calendar, "chat_nudges_enabled", True)),
        qmark="◆",
        style=style,
    ).ask()
    if chat_nudges is None:
        return False
    holidays_enabled = questionary.confirm(
        "Overlay public holidays on the calendar?",
        default=bool(getattr(calendar, "holidays_enabled", True)),
        qmark="◆",
        style=style,
    ).ask()
    if holidays_enabled is None:
        return False

    holidays_country = str(getattr(calendar, "holidays_country", "") or "").strip().upper()
    if holidays_enabled:
        holidays_country = (
            questionary.text(
                "Holiday country code (optional, e.g. US, GB, DE)",
                default=holidays_country,
                qmark="◆",
                style=style,
            ).ask()
            or holidays_country
        ).strip().upper()

    update_calendar_config(
        {
            "enabled": True,
            "reminder_upcoming_minutes": upcoming,
            "reminder_starting_soon_minutes": starting_soon,
            "urgent_interrupts_enabled": bool(urgent_interrupts),
            "urgent_interrupt_persistent": persistent_urgent,
            "conflict_warnings_enabled": bool(conflict_warnings),
            "chat_nudges_enabled": bool(chat_nudges),
            "holidays_enabled": bool(holidays_enabled),
            "holidays_country": holidays_country if holidays_enabled else "",
        }
    )
    print("Calendar setup updated. Reminders will use the new settings on the next scheduler tick.")
    return True


def configure_service_setup(questionary: Any, style: Any) -> bool:
    if shutil.which("systemctl") is None:
        print("systemctl was not found. Skipping service/autostart setup.")
        return True

    enable = questionary.confirm(
        "Install and enable BitBuddy as a background login service?",
        default=True,
        qmark="◆",
        style=style,
    ).ask()
    if enable is None:
        return False
    if enable:
        return enable_service_now()

    disable = questionary.confirm(
        "Disable the BitBuddy user service if it is already installed?",
        default=False,
        qmark="◆",
        style=style,
    ).ask()
    if disable:
        return systemctl_user("disable", "--now", SERVICE_NAME) == 0
    print("Leaving service/autostart unchanged.")
    return True


def enable_service_now() -> bool:
    path = install_service_unit()
    print(f"Installed user service: {path}")
    if systemctl_user("daemon-reload") != 0:
        return False
    if systemctl_user("enable", "--now", SERVICE_NAME) != 0:
        return False
    print("BitBuddy backend service enabled and started.")
    return True


def handle_setup_launch_prompt(questionary: Any, style: Any, service_choice: bool | None = None) -> None:
    service_managed = False
    if service_choice is True:
        service_managed = configure_service_setup(questionary, style)
    elif service_choice is None and shutil.which("systemctl") is not None:
        enable_service = questionary.confirm(
            "Install and enable BitBuddy as a background login service?",
            default=False,
            qmark="◆",
            style=style,
        ).ask()
        if enable_service:
            service_managed = enable_service_now()

    token = get_api_token()
    backend_running = check_backend_health(token=token)
    if service_managed:
        print("BitBuddy backend is managed by the user systemd service.")
    elif backend_running:
        restart = questionary.confirm(
            "BitBuddy server is already running. Restart it now to load setup changes?",
            default=False,
            qmark="◆",
            style=style,
        ).ask()
        if restart:
            restarted = restart_backend_detached()
            print("BitBuddy server restarted." if restarted else "Could not restart automatically. Stop the old server and run `bitbuddy serve`.")
    else:
        start = questionary.confirm(
            "Start BitBuddy server now?",
            default=True,
            qmark="◆",
            style=style,
        ).ask()
        if start:
            start_backend_detached()
            print("BitBuddy server starting in the background.")

    open_dashboard = questionary.confirm(
        "Open the dashboard now?",
        default=True,
        qmark="◆",
        style=style,
    ).ask()
    if open_dashboard:
        start_dashboard_detached()
        print("BitBuddy dashboard starting in the background.")


def start_backend_detached() -> subprocess.Popen[bytes]:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log_path = APP_DIR / "serve.log"
    log = log_path.open("ab")
    return subprocess.Popen([bitbuddy_command(), "serve"], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def start_dashboard_detached() -> subprocess.Popen[bytes]:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log_path = APP_DIR / "dashboard.log"
    log = log_path.open("ab")
    return subprocess.Popen([bitbuddy_command(), "dashboard"], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def restart_backend_detached() -> bool:
    pids = backend_process_ids()
    if not pids:
        return False
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and check_backend_health():
        time.sleep(0.2)
    start_backend_detached()
    return True


def backend_process_ids() -> list[int]:
    try:
        result = subprocess.run(["ps", "-eo", "pid=,cmd="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    pids: list[int] = []
    own_pid = os.getpid()
    for line in result.stdout.splitlines():
        clean = line.strip()
        if not clean:
            continue
        pid_text, _, command = clean.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == own_pid:
            continue
        if "bitbuddy" in command and (" serve" in command or "bitbuddy.server import serve" in command):
            pids.append(pid)
    return pids


def bitbuddy_command() -> str:
    command = shutil.which("bitbuddy")
    if command:
        return command
    candidate = Path(sys.executable).with_name("bitbuddy")
    return str(candidate if candidate.exists() else sys.argv[0])


def user_systemd_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def service_unit_path() -> Path:
    return user_systemd_dir() / SERVICE_NAME


def systemd_quote_arg(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_service_unit() -> str:
    command = systemd_quote_arg(bitbuddy_command())
    return f"""[Unit]
Description=BitBuddy local backend
After=network-online.target

[Service]
Type=simple
ExecStart={command} serve --host 127.0.0.1 --port 8787
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def install_service_unit() -> Path:
    path = service_unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_service_unit(), encoding="utf-8")
    return path


def systemctl_user(*args: str) -> int:
    if shutil.which("systemctl") is None:
        print("systemctl was not found. User systemd service control is unavailable on this system.", file=sys.stderr)
        return 1
    return subprocess.call(["systemctl", "--user", *args])


def journalctl_user(*args: str) -> int:
    if shutil.which("journalctl") is None:
        print("journalctl was not found. Service logs are unavailable on this system.", file=sys.stderr)
        return 1
    return subprocess.call(["journalctl", "--user", "-u", SERVICE_NAME, *args])


def service_install_command(_args: argparse.Namespace) -> int:
    path = install_service_unit()
    print(f"Installed user service: {path}")
    daemon_result = systemctl_user("daemon-reload")
    if daemon_result == 0:
        print("Reloaded user systemd daemon.")
    return daemon_result


def service_enable_command(_args: argparse.Namespace) -> int:
    path = install_service_unit()
    print(f"Installed user service: {path}")
    daemon_result = systemctl_user("daemon-reload")
    if daemon_result != 0:
        return daemon_result
    return systemctl_user("enable", "--now", SERVICE_NAME)


def service_disable_command(_args: argparse.Namespace) -> int:
    return systemctl_user("disable", "--now", SERVICE_NAME)


def service_action_command(args: argparse.Namespace) -> int:
    command = str(args.service_command or "status")
    if command in {"start", "restart"} and not service_unit_path().exists():
        path = install_service_unit()
        print(f"Installed user service: {path}")
        daemon_result = systemctl_user("daemon-reload")
        if daemon_result != 0:
            return daemon_result
    return systemctl_user(command, SERVICE_NAME)


def service_status_command(_args: argparse.Namespace) -> int:
    return systemctl_user("status", SERVICE_NAME)


def service_logs_command(args: argparse.Namespace) -> int:
    journal_args = ["-n", str(max(1, int(args.lines)))]
    if args.follow:
        journal_args.append("-f")
    return journalctl_user(*journal_args)


def setup_positive_int(questionary: Any, style: Any, prompt: str, default: int) -> int | None:
    value = questionary.text(prompt, default=str(default), qmark="◆", style=style).ask()
    if value is None:
        return None
    try:
        parsed = int(str(value).strip() or default)
    except ValueError as error:
        raise ValueError(f"{prompt} must be a whole number.") from error
    if parsed < 1:
        raise ValueError(f"{prompt} must be at least 1.")
    return parsed


def parse_setup_quirks(value: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        clean = " ".join(item.strip().split())[:80]
        key = clean.lower()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
        if len(result) >= 3:
            break
    return result


def run_web(args: argparse.Namespace) -> int:
    return subprocess.call(
        ["npm", "run", "dev", "--", "--host", args.host, "--port", str(args.port)],
        cwd=WEB_DIR,
    )


def run_dashboard(args: argparse.Namespace) -> int:
    web_process: subprocess.Popen[bytes] | None = None
    api_token = get_api_token()
    api_url = f"http://{local_browser_host(args.api_host)}:{int(args.api_port)}"
    dashboard_url = f"http://{local_browser_host(args.host)}:{args.port}"
    launch_url = f"{dashboard_url}?{urlencode({'bitbuddy_token': api_token, 'bitbuddy_api': api_url})}"
    dashboard_url_file = write_private_dashboard_url(launch_url)

    if check_backend_health(args.api_host, int(args.api_port), token=api_token):
        print(f"Using existing BitBuddy backend at {api_url}.")
    else:
        print(f"BitBuddy backend is not running at {api_url}. Start it with `bitbuddy serve`.")

    if wait_for_http(dashboard_url, timeout_seconds=1.5):
        print(f"Using existing BitBuddy dashboard at {dashboard_url}.")
        print(f"Dashboard URL saved to {dashboard_url_file}.")
        if not args.no_open:
            webbrowser.open(launch_url)
        return 0

    print(f"Starting BitBuddy dashboard at {dashboard_url} ...")
    try:
        web_process = subprocess.Popen(
            ["npm", "run", "dev", "--", "--host", args.host, "--port", str(args.port)],
            cwd=WEB_DIR,
        )
        if wait_for_http(dashboard_url, timeout_seconds=20) and not args.no_open:
            webbrowser.open(launch_url)
        elif not args.no_open:
            print(f"Dashboard is starting. Tokenized URL saved to {dashboard_url_file}.")
        print(f"Dashboard URL saved to {dashboard_url_file}.")
        return web_process.wait()
    finally:
        if web_process is not None and web_process.poll() is None:
            terminate_process(web_process)


def run_serve(args: argparse.Namespace) -> int:
    ensure_backend_bind_allowed(str(args.host), bool(getattr(args, "allow_lan", False)))
    get_api_token()
    serve(args.host, args.port)
    return 0


def status_command(args: argparse.Namespace) -> int:
    config = load_config()
    projects = list_projects()
    chat_count = len(list_recent_chats(limit=1000))
    server_ok = check_backend_health()
    print("BitBuddy Status")
    print(f"Home: {APP_DIR}")
    print(f"Config: {CONFIG_PATH}")
    print(f"Backend: {'running' if server_ok else 'not detected'}")
    print(f"Dashboard: {WEB_DIR}")
    print(f"Provider: {provider_display_name(config.provider.type)}{f' / {config.provider.model}' if config.provider.model else ''}")
    try:
        ok, message = ProviderClient(config.provider).health()
        print(f"Provider health: {'ok' if ok else 'problem'} - {message}")
    except Exception as error:
        print(f"Provider health: problem - {error}")
    print(f"Projects: {len(projects)} registered")
    print(f"Sessions: {chat_count} saved")
    print(f"Calendar: {'enabled' if config.calendar.enabled else 'off'}")
    print(f"Email: {'enabled' if config.email.enabled else 'off'}")
    print(f"MCP: {'enabled' if config.mcp.enabled else 'disabled'} ({len(config.mcp_servers)} server(s))")
    if args.doctor:
        from .doctor import run_doctor_checks

        results = run_doctor_checks()
        totals = {status: len([result for result in results if result.status == status]) for status in ("pass", "warn", "fail", "skip")}
        print(f"Doctor: pass={totals['pass']} warn={totals['warn']} fail={totals['fail']} skip={totals['skip']}")
    return 0


def check_backend_health(host: str = "127.0.0.1", port: int = 8787, *, token: str = "") -> bool:
    return wait_for_backend(host, port, timeout_seconds=1.5, token=token)


def wait_for_backend(host: str = "127.0.0.1", port: int = 8787, *, timeout_seconds: float = 10, token: str = "") -> bool:
    return wait_for_http(f"http://{local_browser_host(host)}:{int(port)}/health", timeout_seconds=timeout_seconds, require_2xx=True, token=token)


def wait_for_http(url: str, *, timeout_seconds: float = 10, require_2xx: bool = False, token: str = "") -> bool:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers={API_TOKEN_HEADER: token} if token else {})
            with urllib.request.urlopen(request, timeout=1.5) as response:
                return 200 <= response.status < (300 if require_2xx else 500)
        except OSError as error:
            last_error = str(error)
            time.sleep(0.25)
    return False


def local_browser_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::", ""} else str(host)


def write_private_dashboard_url(url: str) -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    path = APP_DIR / "dashboard.url"
    tmp_path = path.with_suffix(".url.tmp")
    tmp_path.write_text(url + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
    os.chmod(path, 0o600)
    return path


def ensure_backend_bind_allowed(host: str, allow_lan: bool) -> None:
    if is_loopback_host(host):
        return
    if not allow_lan:
        raise ValueError("Refusing to bind BitBuddy backend to a non-loopback address without --allow-lan.")
    print("Warning: BitBuddy backend is being exposed beyond localhost. Keep the API token private and only use trusted networks.")


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def config_show_command(_args: argparse.Namespace) -> int:
    load_config()
    print(CONFIG_PATH.read_text(encoding="utf-8"), end="")
    return 0


def config_path_command(_args: argparse.Namespace) -> int:
    load_config()
    print(CONFIG_PATH)
    return 0


def config_edit_command(_args: argparse.Namespace) -> int:
    load_config()
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise ValueError("Set $EDITOR or $VISUAL to edit config.yaml from the CLI.")
    return subprocess.call([*shlex.split(editor), str(CONFIG_PATH)])


def config_gmail_full_access_command(args: argparse.Namespace) -> int:
    config = update_email_config({"gmail_full_mail_access": bool(args.enable)})
    if config.email.gmail_full_mail_access:
        print("Gmail full mail access enabled for the next reconnect.")
        print("Add https://mail.google.com/ in Google Cloud OAuth Data Access, save, then run Gmail reconnect in Settings.")
    else:
        print("Gmail full mail access disabled. The next reconnect will use the safer Gmail modify scope.")
    return 0


def model_command(args: argparse.Namespace) -> int:
    config = load_config()
    if args.list:
        return model_list_command(config)
    if args.set_provider:
        return model_set_active_command(args.set_provider, config)
    if args.add:
        return model_add_command(config)
    return model_interactive_command(config)


def model_list_command(config: object) -> int:
    providers = provider_entries_from_config(config)
    if not providers:
        print("No model providers configured. Run `bitbuddy model --add` or `bitbuddy setup`.")
        return 0
    active = getattr(config, "active_provider", "")
    for provider in providers:
        key = str(provider.get("key") or provider.get("type") or "")
        marker = "*" if key == active else " "
        model = str(provider.get("model") or "")
        print(f"{marker} {key}\t{provider_display_name(str(provider.get('type') or 'none'))}\t{model}")
    return 0


def model_set_active_command(active_provider: str, config: object) -> int:
    providers = provider_entries_from_config(config)
    keys = {str(provider.get("key") or provider.get("type") or "") for provider in providers}
    if active_provider not in keys:
        raise ValueError(f"Unknown provider `{active_provider}`. Run `bitbuddy model --list`.")
    update_model_runtime_config({"providers": providers, "active_provider": active_provider})
    print(f"Active model provider set to {active_provider}.")
    return 0


def model_add_command(config: object) -> int:
    questionary, style = load_questionary_for_cli()
    providers = provider_entries_from_config(config)
    choices = ["Ollama", "llama.cpp", "OpenAI API", "Codex", "Anthropic"]
    default_label = provider_label_from_key(getattr(getattr(config, "provider", None), "type", "ollama"))
    label = questionary.select(
        "Add or update provider",
        choices=choices,
        default=default_label if default_label in choices else "Ollama",
        qmark="◆",
        pointer="›",
        style=style,
    ).ask()
    if label is None:
        return 1
    entry = configure_provider_entry(questionary, style, label, providers)
    next_providers = [provider for provider in providers if provider.get("type") != entry.get("type")]
    next_providers.append(entry)
    active_provider = str(entry.get("key") or entry.get("type") or "none")
    update_model_runtime_config({"providers": next_providers, "active_provider": active_provider})
    print(f"Configured {provider_display_name(str(entry.get('type') or 'none'))} and made it active.")
    return 0


def model_interactive_command(config: object) -> int:
    providers = provider_entries_from_config(config)
    if not providers:
        return model_add_command(config)
    questionary, style = load_questionary_for_cli()
    choices = [provider_choice_label(provider) for provider in providers]
    choices.append("Add or update provider")
    selected = questionary.select("Choose active model provider", choices=choices, qmark="◆", pointer="›", style=style).ask()
    if selected is None:
        return 1
    if selected == "Add or update provider":
        return model_add_command(config)
    return model_set_active_command(provider_type_from_choice_label(selected), config)


def load_questionary_for_cli() -> tuple[Any, Any]:
    try:
        import questionary
        from questionary import Style
    except ImportError as error:
        raise ValueError("questionary is required. Install this package with `pip install -e .` first.") from error
    return questionary, Style(
        [
            ("qmark", "fg:#79b8ff bold"),
            ("question", "fg:#eef5ff bold"),
            ("answer", "fg:#6ee7b7 bold"),
            ("pointer", "fg:#79b8ff bold"),
            ("highlighted", "fg:#eef5ff noreverse noinherit"),
            ("selected", "fg:#eef5ff noreverse noinherit"),
            ("instruction", "fg:#9fb2ca"),
            ("text", "fg:#eef5ff"),
        ]
    )


def logs_command(args: argparse.Namespace) -> int:
    seen = 0
    while True:
        rows = filtered_activity(args.kind, max(1, args.limit))
        rows_to_print = [row for row in reversed(rows) if int(row["id"]) > seen]
        for row in rows_to_print:
            print_activity_row(row, json_output=args.json)
            seen = max(seen, int(row["id"]))
        if not args.follow:
            return 0
        time.sleep(1)


def filtered_activity(kind: str, limit: int) -> list[dict[str, Any]]:
    rows = list_activity(limit=max(limit * 4, limit))
    if kind == "errors":
        rows = [row for row in rows if is_error_activity(row)]
    return rows[:limit]


def is_error_activity(row: dict[str, Any]) -> bool:
    text = f"{row.get('kind', '')} {row.get('message', '')}".casefold()
    return any(token in text for token in ("error", "fail", "failed", "crash", "exception"))


def print_activity_row(row: dict[str, Any], *, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(row, sort_keys=True))
        return
    print(f"{row['created_at']}\t{row['kind']}\t{row['message']}")


def sessions_list_command(args: argparse.Namespace) -> int:
    sessions = list_recent_chats(limit=max(1, getattr(args, "limit", 20)), search=getattr(args, "search", ""))
    if not sessions:
        print("No saved sessions.")
        return 0
    for session in sessions:
        print(f"{session.id}\t{session.updated_at}\t{session.mode}\t{session.title}")
    return 0


def sessions_show_command(args: argparse.Namespace) -> int:
    chat = get_chat(args.session)
    print(f"{chat['title']} ({chat['id']})")
    print(f"mode={chat['mode']} created={chat['created_at']} updated={chat['updated_at']}")
    print()
    for message in chat["messages"]:
        role = message.get("role") or message.get("kind") or "message"
        content = str(message.get("content") or message.get("summary") or "").strip()
        if content:
            print(f"[{role}] {content}")
    return 0


def sessions_export_command(args: argparse.Namespace) -> int:
    payload = json.dumps(get_chat(args.session), indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"Exported session to {args.output}")
    else:
        print(payload, end="")
    return 0


def sessions_rename_command(args: argparse.Namespace) -> int:
    title = " ".join(args.title.split())[:80]
    if not title:
        raise ValueError("Session title cannot be blank.")
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute("update chats set title = ?, updated_at = current_timestamp where id = ?", (title, args.session))
    if cursor.rowcount == 0:
        raise ValueError(f"Unknown session: {args.session}")
    print(f"Renamed session {args.session} to {title}.")
    return 0


def sessions_delete_command(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to delete without --yes.")
    if not delete_chat(args.session):
        raise ValueError(f"Unknown session: {args.session}")
    print(f"Deleted session {args.session}.")
    return 0


def sessions_prune_command(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("Refusing to prune without --yes.")
    keep = max(0, int(args.keep))
    sessions = list_recent_chats(limit=100000)
    stale = sessions[keep:]
    for session in stale:
        delete_chat(session.id)
    print(f"Pruned {len(stale)} session(s); kept {min(keep, len(sessions))}.")
    return 0


def backup_command(args: argparse.Namespace) -> int:
    ensure_app_dirs()
    output = Path(args.output) if args.output else Path.cwd() / f"bitbuddy-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in APP_DIR.rglob("*"):
            if path.is_symlink() or path.is_dir():
                continue
            if path.name == "secrets.json" and not args.include_secrets:
                continue
            try:
                archive.write(path, path.relative_to(APP_DIR.parent))
            except FileNotFoundError:
                continue
    print(f"Backup written: {output}")
    if not args.include_secrets:
        print("Note: secrets.json was excluded. Use --include-secrets only for trusted local backups.")
    return 0


def update_command(args: argparse.Namespace) -> int:
    root = source_checkout_root()
    branch = str(getattr(args, "branch", "stable") or "stable").strip()
    if not branch:
        raise ValueError("Update branch cannot be blank.")
    if not (root / ".git").exists():
        raise ValueError(
            "BitBuddy update requires a Git source checkout. Reinstall from https://getbitbuddy.com if this install was copied from a wheel or package manager."
        )
    if shutil.which("git") is None:
        raise ValueError("Missing 'git'. Install it, then rerun `bitbuddy update`.")
    if shutil.which("npm") is None and (root / "web" / "package.json").exists():
        raise ValueError("Missing 'npm'. Install Node.js LTS, then rerun `bitbuddy update`.")

    dirty = checkout_has_local_changes(root)
    stash_ref = ""
    if dirty:
        if args.no_autostash:
            raise ValueError("Refusing to update because the BitBuddy checkout has local changes. Commit/stash them or rerun without --no-autostash.")
        stash_ref = stash_local_changes(root)

    print(f"Updating BitBuddy source checkout: {root}")
    try:
        run_update_step(["git", "-C", str(root), "fetch", "--prune", "origin", branch])
        run_update_step(["git", "-C", str(root), "pull", "--ff-only", "origin", branch])
        run_update_step([sys.executable, "-m", "pip", "install", "-e", str(root)])

        web_dir = root / "web"
        if (web_dir / "package.json").exists():
            run_update_step(["npm", "install", "--prefix", str(web_dir)])
        else:
            print("Skipping web dependency update; web/package.json was not found.")

        run_update_step([sys.executable, "-m", "bitbuddy", "--help"])
        if not args.skip_doctor:
            doctor = subprocess.run([sys.executable, "-m", "bitbuddy", "doctor"])
            if doctor.returncode != 0:
                print("BitBuddy updated, but doctor reported issues. Run `bitbuddy doctor` for details.", file=sys.stderr)
    finally:
        if stash_ref:
            restore_stashed_changes(root, stash_ref)

    print("BitBuddy updated.")
    return 0


def source_checkout_root() -> Path:
    package_file = Path(__file__).resolve()
    for parent in package_file.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "bitbuddy").is_dir():
            return parent
    return package_file.parents[2]


def checkout_has_local_changes(root: Path) -> bool:
    result = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError("Could not inspect the BitBuddy checkout for local changes.")
    return bool(result.stdout.strip())


def stash_local_changes(root: Path) -> str:
    stash_name = f"bitbuddy-update-autostash-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    print("Local changes detected; stashing before update.")
    run_update_step(["git", "-C", str(root), "stash", "push", "--include-untracked", "-m", stash_name])
    return "stash@{0}"


def restore_stashed_changes(root: Path, stash_ref: str) -> None:
    print("Restoring local changes after update.")
    apply = subprocess.run(["git", "-C", str(root), "stash", "apply", stash_ref])
    if apply.returncode != 0:
        print(
            f"BitBuddy updated, but local changes could not be restored cleanly. They remain in git stash. Resolve manually with: git -C {shlex.quote(str(root))} stash apply {shlex.quote(stash_ref)}",
            file=sys.stderr,
        )
        return
    drop = subprocess.run(["git", "-C", str(root), "stash", "drop", stash_ref])
    if drop.returncode != 0:
        print("Local changes were restored, but the temporary stash could not be dropped automatically.", file=sys.stderr)


def run_update_step(command: list[str]) -> None:
    print(f"$ {shlex.join(command)}")
    result = subprocess.run(command)
    if result.returncode != 0:
        raise ValueError(f"Update step failed: {shlex.join(command)}")


def completion_command(args: argparse.Namespace) -> int:
    commands = "setup serve web dashboard status doctor config model logs sessions backup update completion provider mcp projects librarian"
    if args.shell == "bash":
        print(f"complete -W '{commands}' bitbuddy")
    elif args.shell == "zsh":
        print(f"#compdef bitbuddy\n_arguments '1:command:({commands})'")
    else:
        for command in commands.split():
            print(f"complete -c bitbuddy -f -a {command}")
    return 0


def doctor_command(_args: argparse.Namespace) -> int:
    from .doctor import doctor_exit_code, render_doctor_report, run_doctor_checks

    try:
        results = run_doctor_checks()
    except Exception as error:
        print(f"BitBuddy Doctor crashed: {error}", file=sys.stderr)
        return 2
    print(render_doctor_report(results), end="")
    return doctor_exit_code(results)


def doctor_fix_command(_args: argparse.Namespace) -> int:
    from .doctor.fixers import render_fix_report, run_doctor_fix

    try:
        fixes, after, exit_code = run_doctor_fix()
    except Exception as error:
        print(f"BitBuddy Doctor crashed while fixing: {error}", file=sys.stderr)
        return 2
    print(render_fix_report(fixes, after), end="")
    return exit_code


def provider_help(_args: argparse.Namespace) -> int:
    print("usage: bitbuddy provider {check,models,stream-test} ...")
    print()
    print("Inspect the active model provider.")
    return 0


def provider_check_command(_args: argparse.Namespace) -> int:
    client = ProviderClient(load_config().provider)
    ok, message = client.health()
    print(message)
    return 0 if ok else 1


def provider_stream_test_command(args: argparse.Namespace) -> int:
    config = load_config()
    client = ProviderClient(config.provider)
    messages = [{"role": "user", "content": args.prompt}]
    for chunk in client.stream_chat(messages):
        prefix = "[thinking] " if chunk.kind == "thinking" else "[response] "
        print(f"{prefix}{chunk.text}", end="", flush=True)
    print()
    return 0


def provider_models_command(_args: argparse.Namespace) -> int:
    client = ProviderClient(load_config().provider)
    models = client.models()
    if not models:
        print("No models reported by provider.")
        return 0
    for model in models:
        print(model)
    return 0


def mcp_help(_args: argparse.Namespace) -> int:
    print("usage: bitbuddy mcp {list,install-computer-use-linux,doctor-computer-use-linux,add-computer-use-linux} ...")
    print()
    print("Manage MCP tool servers.")
    return 0


def mcp_list_command(_args: argparse.Namespace) -> int:
    config = load_config()
    servers = config.mcp_servers
    print(f"MCP discovery: {'enabled' if config.mcp.enabled else 'disabled'}")
    if not servers:
        print("No MCP servers configured.")
        return 0
    for server in servers:
        status = "enabled" if server.enabled else "disabled"
        argv = " ".join([server.command, *server.args])
        print(f"{server.name}\t{status}\t{argv}")
    return 0


def mcp_add_computer_use_linux_command(args: argparse.Namespace) -> int:
    if args.command == "managed:computer-use-linux":
        ok, message = provision_computer_use_linux(install=not args.no_install)
        print(message)
        config = load_config()
    else:
        ok = True
        config = upsert_mcp_server(
            "computer-use-linux",
            args.command,
            ["mcp"],
            timeout=120,
            connect_timeout=30,
            enabled=True,
        )
    server = next(server for server in config.mcp_servers if server.name == "computer_use_linux")
    print(f"Configured MCP server: {server.name}")
    print(f"Command: {' '.join([server.command, *server.args])}")
    print("Run `bitbuddy mcp doctor-computer-use-linux` to verify desktop readiness.")
    return 0 if ok else 1


def provision_computer_use_linux(install: bool = True) -> tuple[bool, str]:
    """Ensure BitBuddy is configured for Linux desktop-control MCP support."""
    if not sys.platform.startswith("linux"):
        return False, "computer-use-linux managed install is only supported on Linux."
    update_mcp_config({"enabled": True})
    config = upsert_mcp_server(
        "computer-use-linux",
        "managed:computer-use-linux",
        ["mcp"],
        timeout=120,
        connect_timeout=30,
        enabled=True,
    )
    server = next(server for server in config.mcp_servers if server.name == "computer_use_linux")
    if not install:
        return True, f"Configured MCP server: {server.name}"

    try:
        status = computer_use_linux_status()
        if not status.available or status.source != "managed":
            status = install_computer_use_linux()
    except Exception as error:
        return False, f"Desktop-control install failed: {error}"
    return status.available, status.message


def mcp_install_computer_use_linux_command(_args: argparse.Namespace) -> int:
    status = install_computer_use_linux()
    print(status.message)
    print(f"Path: {status.path}")
    return 0 if status.available else 1


def mcp_doctor_computer_use_linux_command(_args: argparse.Namespace) -> int:
    status = computer_use_linux_status()
    if not status.available:
        print(status.message, file=sys.stderr)
        return 1
    command = resolve_managed_command("managed:computer-use-linux")
    return subprocess.call([command, "doctor"])


def projects_help(_args: argparse.Namespace) -> int:
    print("usage: bitbuddy projects {add,list,index,map} ...")
    print()
    print("Manage read-only project memories.")
    return 0


def add_project_command(args: argparse.Namespace) -> int:
    project = register_project(args.name, args.paths)
    print(f"Registered read-only project memory: {project.name}")
    print(f"Project id: {project.id}")
    print(f"Database: {project.database_path}")
    return 0


def list_projects_command(_args: argparse.Namespace) -> int:
    projects = list_projects()
    if not projects:
        print("No projects registered yet.")
        return 0
    for project in projects:
        paths = ", ".join(str(path) for path in project.paths)
        print(f"{project.id}\t{project.name}\t{paths}")
    return 0


def index_project_command(args: argparse.Namespace) -> int:
    result = index_project(args.project)
    print(f"Indexed {result.project.name}")
    print(f"Scanned: {result.scanned}")
    print(f"Changed: {result.changed}")
    print(f"Deleted: {result.deleted}")
    print(f"Skipped: {result.skipped}")
    return 0


def project_map_command(args: argparse.Namespace) -> int:
    print(project_map(args.project, limit=args.limit))
    return 0


# ---------------------------------------------------------------------------
# Librarian CLI handlers
# ---------------------------------------------------------------------------

def librarian_add_command(args: argparse.Namespace) -> int:
    card = regenerate_card(args.project)
    if card is None:
        print(f"No card for '{args.project}'. Make sure the project is registered and indexed first.")
        return 1
    print(f"Card built for {card.project_name} ({card.project_id})")
    print()
    print(format_whisper([card]))
    return 0


def librarian_list_command(_args: argparse.Namespace) -> int:
    cards = list_cards()
    if not cards:
        print("No librarian cards yet. Run `bitbuddy librarian add <project>` first.")
        return 0
    for card in cards:
        fact_count = len(card.verified_facts)
        file_count = len(card.important_files)
        print(f"  {card.project_id}\t{card.project_name}\tfacts={fact_count}\tfiles={file_count}")
    return 0


def librarian_show_command(args: argparse.Namespace) -> int:
    card = get_card(args.project)
    if card is None:
        print(f"No card for '{args.project}'. Run `bitbuddy librarian add {args.project}` first.")
        return 1
    print(format_whisper([card]))
    return 0


def librarian_reset_command(args: argparse.Namespace) -> int:
    card = regenerate_card(args.project)
    if card is None:
        print(f"Could not rebuild card for '{args.project}'.")
        return 1
    print(f"Regenerated card for {card.project_name} ({card.project_id})")
    return 0


def librarian_index_all_command(_args: argparse.Namespace) -> int:
    cards = index_all_projects()
    if not cards:
        print("No indexed projects found. Register and index projects first.")
        return 1
    print(f"Indexed {len(cards)} librarian cards:")
    for card in cards:
        print(f"  {card.project_id}\t{card.project_name}")
    return 0


def librarian_test_whisper_command(args: argparse.Namespace) -> int:
    query = args.query or "test"
    cards = get_relevant_whisper(query, max_cards=3)
    if not cards:
        print(f"No relevant cards for query: {query}")
        return 0
    print(f"Query: {query}")
    print()
    for card in cards:
        score = _score_card_debug(card, query)
        print(f"  Score: {score:.1f}  {card.project_name} ({card.project_id})")
    print()
    print("--- Whisper output ---")
    print(format_whisper(cards))
    return 0


def _score_card_debug(card, query):
    """Helper for the test command — re-exports from librarian module."""
    from .librarian import _score_card
    return _score_card(card, query)
