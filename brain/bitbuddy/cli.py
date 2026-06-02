from __future__ import annotations

import argparse
import subprocess
import sys

from .activity import log_activity
from .config import ProviderConfig, load_config, update_mcp_config, upsert_mcp_server, validate_timezone, write_config
from .personality import BUILTIN_PERSONALITIES
from .paths import CONFIG_PATH, PERSONALITIES_DIR, WEB_DIR, ensure_app_dirs
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
    serve_parser.set_defaults(handler=run_serve)

    web_parser = subparsers.add_parser("web", help="Run the SvelteKit/Vite web app.")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host for the dev server.")
    web_parser.add_argument("--port", default="5173", help="Port for the dev server.")
    web_parser.set_defaults(handler=run_web)

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

    return parser


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
            choices=["Modify current setup", "Keep current setup", "Start new setup"],
            default="Modify current setup",
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if setup_action is None:
            return 1
        if setup_action == "Keep current setup":
            print(f"Keeping current setup at {CONFIG_PATH}")
            print("Run `bitbuddy serve` when you are ready.")
            return 0

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
    location_label_default = ""
    timezone_default = "UTC"
    locale_default = "en-US"
    max_tool_rounds_default = 99
    if setup_action == "Modify current setup" and current_config is not None:
        buddy_name_default = current_config.name
        presentation_default = current_config.presentation.style
        pronouns_default = current_config.presentation.pronouns
        personality_id_default = current_config.personality.id
        expressiveness_default = current_config.personality.expressiveness
        proactivity_default = current_config.personality.proactivity
        location_label_default = current_config.user_context.location_label
        timezone_default = current_config.user_context.timezone
        locale_default = current_config.user_context.locale
        max_tool_rounds_default = current_config.chat.max_tool_rounds
        provider_default = provider_label_from_key(current_config.provider.type)
        provider_url_default = current_config.provider.url or provider_url_default_for(current_config.provider.type)
        provider_model_default = current_config.provider.model
        scan_interval_default = current_config.project_scan_interval_seconds

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
    max_tool_rounds_answer = questionary.text(
        "Max tool calls per chat turn",
        default=str(max_tool_rounds_default),
        qmark="◆",
        style=style,
    ).ask()
    max_tool_rounds = parse_tool_round_limit(max_tool_rounds_answer or str(max_tool_rounds_default))

    configure_provider = True
    configure_project_memory: bool | None = None
    if setup_action == "Modify current setup":
        optional_sections = questionary.checkbox(
            "Which optional setup sections do you want to configure now?",
            choices=[
                questionary.Choice("Local model provider", checked=False),
                questionary.Choice("Read-only project memory", checked=False),
            ],
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if optional_sections is None:
            return 1
        configure_provider = "Local model provider" in optional_sections
        configure_project_memory = "Read-only project memory" in optional_sections

    provider_config = existing_or_empty_provider_config(current_config)
    provider = provider_config.type
    provider_url = provider_config.url
    provider_model = provider_config.model
    skip_preserved_existing = False
    if configure_provider:
        provider_label = questionary.select(
            "Choose your local model provider",
            choices=["Ollama", "llama.cpp", "Skip for now"],
            default=provider_default,
            qmark="◆",
            pointer="›",
            style=style,
        ).ask()
        if provider_label is None:
            return 1
        provider_config, skip_preserved_existing = provider_config_from_setup_choice(provider_label, setup_action, current_config)
        provider = provider_config.type
        provider_url = provider_config.url
        provider_model = provider_config.model

    if configure_provider and provider != "none" and not skip_preserved_existing:
        default_url = (
            provider_url_default
            if setup_action == "Modify current setup" and provider == current_provider_key(current_config) and provider_url_default
            else provider_url_default_for(provider)
        )
        provider_url = (
            questionary.text(
                provider_url_question(provider),
                default=default_url,
                qmark="◆",
                style=style,
            ).ask()
            or default_url
        )
        detected_models = detect_provider_models(provider, provider_url)
        default_model = provider_model or (detected_models[0] if detected_models else "")
        if detected_models:
            print(f"Found model: {default_model}")
        else:
            print("No model name found automatically. You can enter one now or leave it blank.")
        provider_model = (
            questionary.text(
                "Model name",
                default=default_model,
                qmark="◆",
                style=style,
            ).ask()
            or default_model
        )
    elif skip_preserved_existing:
        print("Keeping existing provider settings because setup was skipped.")

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
    }
    user_context_config = {
        "location_label": location_label,
        "timezone": timezone,
        "locale": locale,
    }
    chat_config = {
        "max_tool_rounds": max_tool_rounds,
    }
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

    print()
    print("Setup complete. Run `bitbuddy serve` to start the BitBuddy backend server.")
    return 0


def provider_url_question(provider: str) -> str:
    if provider == "llama.cpp":
        return "llama.cpp server address"
    if provider == "ollama":
        return "Ollama server address"
    return "Provider URL"


def provider_label_from_key(provider: str) -> str:
    if provider == "ollama":
        return "Ollama"
    if provider == "llama.cpp":
        return "llama.cpp"
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


def run_web(args: argparse.Namespace) -> int:
    return subprocess.call(
        ["npm", "run", "dev", "--", "--host", args.host, "--port", str(args.port)],
        cwd=WEB_DIR,
    )


def run_serve(args: argparse.Namespace) -> int:
    serve(args.host, args.port)
    return 0


def provider_help(_args: argparse.Namespace) -> int:
    print("usage: bitbuddy provider {check,models,stream-test} ...")
    print()
    print("Inspect the configured local model provider.")
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
