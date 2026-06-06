from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .calendar.secrets import delete_credentials, get_credentials, put_credentials
from .paths import CONFIG_PATH, PERSONALITY_PATH, ensure_app_dirs
from .personality import (
    PersonalitySelection,
    PresentationConfig,
    default_personality_selection_config,
    default_presentation_config,
    parse_personality_selection,
    parse_presentation,
    seed_builtin_personality_files,
    selected_personality_to_legacy_dict,
    load_selected_personality,
    write_legacy_personality_export,
)


DEFAULT_PERSONALITY = {
    "name": "BitBuddy",
    "description": "A local companion that learns your projects, grows with you, and keeps its memory close to home.",
    "style": {
        "tone": "friendly",
        "verbosity": "concise",
        "default_mode": "chat",
    },
}

DEFAULT_AUTONOMY_IDLE_DELAY_SECONDS = 300
DEFAULT_AUTONOMY_BACKOFF_MULTIPLIER = 1.5
DEFAULT_AUTONOMY_MAX_DELAY_SECONDS = 1800
DEFAULT_DREAMING_BEDTIME = "23:00"
DEFAULT_DREAMING_WAKE_TIME = "08:00"
PROVIDER_TYPES = {"none", "ollama", "llama.cpp", "openai", "codex", "anthropic"}
CLOUD_PROVIDER_TYPES = {"openai", "anthropic"}
URL_PROVIDER_TYPES = {"ollama", "llama.cpp", "openai", "anthropic"}
DEFAULT_PROVIDER_URLS = {
    "ollama": "http://127.0.0.1:11434",
    "llama.cpp": "http://127.0.0.1:8080",
    "openai": "https://api.openai.com",
    "codex": "codex://chatgpt",
    "anthropic": "https://api.anthropic.com",
}
DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-4.1",
    "codex": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
}


@dataclass(frozen=True)
class ProviderConfig:
    type: str
    url: str
    model: str
    embedding_model: str = "nomic-embed-text"
    embedding_url: str = ""
    native_tools: str = "auto"
    key: str = ""
    api_key: str = ""
    api_key_ref: str = ""
    has_api_key: bool = False


@dataclass(frozen=True)
class UserContextConfig:
    location_label: str
    timezone: str
    locale: str


@dataclass(frozen=True)
class WebSearchConfig:
    enabled: bool
    provider: str
    url: str
    startup_command: str
    max_results: int


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: str
    args: tuple[str, ...]
    env: dict[str, str]
    timeout: float
    connect_timeout: float
    enabled: bool


@dataclass(frozen=True)
class McpConfig:
    enabled: bool


@dataclass(frozen=True)
class ChatConfig:
    return_greeting_enabled: bool
    return_greeting_idle_minutes: int
    return_greeting_phrases: tuple[str, ...]
    max_tool_rounds: int
    reasoning_budget_tokens: int


@dataclass(frozen=True)
class AutonomyConfig:
    enabled: bool
    run_after_idle_consolidation: bool
    idle_delay_seconds: float
    repeat_idle_cycles: bool
    idle_backoff_multiplier: float
    idle_max_delay_seconds: float
    max_actions_per_cycle: int
    max_pending_questions: int
    max_pending_comments: int
    max_new_questions_per_cycle: int
    max_autonomous_deliveries_per_day: int
    web_search: WebSearchConfig


@dataclass(frozen=True)
class DreamingConfig:
    enabled: bool
    bedtime: str
    wake_time: str
    goodnight_triggers: tuple[str, ...]
    goodmorning_triggers: tuple[str, ...]
    idle_before_dream_minutes: int
    minimum_dream_window_minutes: int
    max_dream_tasks_per_night: int
    allow_post_dream_autonomy_rounds: int
    soft_delete_memories: bool
    quiet_mode_after_bedtime: bool
    goodnight_immediate_winddown: bool
    stale_intention_days: int
    low_priority_stale_intention_days: int
    self_note_injection_enabled: bool


@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool = False
    default_provider: str = "local"
    reminder_upcoming_minutes: int = 60
    reminder_starting_soon_minutes: int = 15
    urgent_interrupts_enabled: bool = True
    urgent_interrupt_persistent: bool = True
    conflict_warnings_enabled: bool = True
    free_day_summary_enabled: bool = True
    chat_nudges_enabled: bool = True
    scheduler_tick_seconds: int = 60
    holidays_enabled: bool = True
    holidays_country: str = ""


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool = False
    provider: str = "imap"
    account_label: str = ""
    email_address: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_security: str = "ssl"
    username: str = ""
    credentials_ref: str = ""
    gmail_client_id: str = ""
    gmail_credentials_ref: str = ""
    gmail_token_ref: str = ""
    gmail_redirect_uri: str = "http://localhost:8787/email/gmail/callback"
    default_mailbox: str = "INBOX"
    max_preview_messages: int = 50


@dataclass(frozen=True)
class BitBuddyConfig:
    name: str
    provider: ProviderConfig
    providers: tuple[ProviderConfig, ...]
    active_provider: str
    presentation: PresentationConfig
    personality: PersonalitySelection
    user_context: UserContextConfig
    chat: ChatConfig
    autonomy: AutonomyConfig
    dreaming: DreamingConfig
    calendar: CalendarConfig
    email: EmailConfig
    mcp: McpConfig
    mcp_servers: tuple[McpServerConfig, ...]
    project_scan_interval_seconds: int
    idle_consolidation_enabled: bool
    idle_consolidation_delay_seconds: float
    idle_consolidation_recent_message_count: int
    idle_consolidation_max_tool_rounds: int
    idle_consolidation_max_actions: int
    config_path: Path = CONFIG_PATH


def default_config(
    provider: str = "none",
    url: str = "",
    model: str = "",
    project_scan_interval_seconds: int = 60,
    name: str = "BitBuddy",
) -> dict[str, Any]:
    return {
        "name": name,
        "home": "~/.bitbuddy",
        "permissions": {
            "home_directory_default": "denied",
            "project_paths": "read-only",
            "reference_paths": "read-only",
        },
        "provider": {
            "type": provider,
            "url": url,
            "model": model,
        },
        "providers": [
            {
                "type": provider,
                "url": url,
                "model": model,
            }
        ] if provider != "none" else [],
        "active_provider": provider if provider != "none" else "none",
        "user_context": {
            "location_label": "",
            "timezone": "UTC",
            "locale": "en-US",
        },
        "presentation": default_presentation_config(),
        "personality": default_personality_selection_config(),
        "streams": {
            "thinking": "separate",
            "response": "separate",
        },
        "server": {
            "host": "127.0.0.1",
            "port": 8787,
        },
        "chat": {
            "return_greeting_enabled": True,
            "return_greeting_idle_minutes": 60,
            "return_greeting_phrases": ["Hey, welcome back.", "Hi, welcome back."],
            "max_tool_rounds": 99,
            "reasoning_budget_tokens": -1,
        },
        "autonomy": {
            "enabled": True,
            "run_after_idle_consolidation": True,
            "idle_delay_seconds": DEFAULT_AUTONOMY_IDLE_DELAY_SECONDS,
            "repeat_idle_cycles": True,
            "idle_backoff_multiplier": DEFAULT_AUTONOMY_BACKOFF_MULTIPLIER,
            "idle_max_delay_seconds": DEFAULT_AUTONOMY_MAX_DELAY_SECONDS,
            "max_actions_per_cycle": 1,
            "max_pending_questions": 12,
            "max_pending_comments": 12,
            "max_new_questions_per_cycle": 1,
            "max_autonomous_deliveries_per_day": 10,
            "web_search": {
                "enabled": True,
                "provider": "searxng",
                "url": "http://127.0.0.1:8888",
                "startup_command": "managed",
                "max_results": 5,
            },
        },
        "calendar": {
            "enabled": False,
            "default_provider": "local",
            "reminder_upcoming_minutes": 60,
            "reminder_starting_soon_minutes": 15,
            "urgent_interrupts_enabled": True,
            "urgent_interrupt_persistent": True,
            "conflict_warnings_enabled": True,
            "free_day_summary_enabled": True,
            "chat_nudges_enabled": True,
            "scheduler_tick_seconds": 60,
            "holidays_enabled": True,
            "holidays_country": "",
        },
        "email": {
            "enabled": False,
            "provider": "imap",
            "account_label": "",
            "email_address": "",
            "imap_host": "",
            "imap_port": 993,
            "imap_security": "ssl",
            "username": "",
            "credentials_ref": "",
            "gmail_client_id": "",
            "gmail_credentials_ref": "",
            "gmail_token_ref": "",
            "gmail_redirect_uri": "http://localhost:8787/email/gmail/callback",
            "default_mailbox": "INBOX",
            "max_preview_messages": 50,
        },
        "mcp": {
            "enabled": False,
        },
        "mcp_servers": {},
        "dreaming": {
            "enabled": True,
            "bedtime": DEFAULT_DREAMING_BEDTIME,
            "wake_time": DEFAULT_DREAMING_WAKE_TIME,
            "goodnight_triggers": ["goodnight", "good night"],
            "goodmorning_triggers": ["good morning", "morning"],
            "idle_before_dream_minutes": 30,
            "minimum_dream_window_minutes": 45,
            "max_dream_tasks_per_night": 3,
            "allow_post_dream_autonomy_rounds": 0,
            "soft_delete_memories": True,
            "quiet_mode_after_bedtime": True,
            "goodnight_immediate_winddown": False,
            "stale_intention_days": 14,
            "low_priority_stale_intention_days": 7,
            "self_note_injection_enabled": False,
        },
        "memories": {
            "project_database_root": "~/.bitbuddy/projects",
            "max_file_bytes": 750_000,
            "project_scan_interval_seconds": project_scan_interval_seconds,
            "idle_consolidation_enabled": True,
            "idle_consolidation_delay_seconds": 20,
            "idle_consolidation_recent_message_count": 30,
            "idle_consolidation_max_tool_rounds": 12,
            "idle_consolidation_max_actions": 8,
        },
    }


def write_config(
    provider: str,
    url: str,
    model: str = "",
    project_scan_interval_seconds: int = 60,
    name: str = "BitBuddy",
    presentation: dict[str, Any] | None = None,
    personality: dict[str, Any] | None = None,
    user_context: dict[str, Any] | None = None,
    chat_config: dict[str, Any] | None = None,
    preserve_existing: bool = False,
) -> None:
    ensure_app_dirs()
    seed_builtin_personality_files()
    data = default_config(provider, url, model, project_scan_interval_seconds, name)
    if preserve_existing and CONFIG_PATH.exists():
        existing = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        if isinstance(existing, dict):
            data = deep_merge(data, existing)
            data["name"] = name
            data["provider"] = {"type": provider, "url": url, "model": model}
            data["providers"] = [{"type": provider, "url": url, "model": model}] if provider != "none" else []
            data["active_provider"] = provider if provider != "none" else "none"
            memories = data.get("memories") if isinstance(data.get("memories"), dict) else {}
            memories["project_scan_interval_seconds"] = project_scan_interval_seconds
            data["memories"] = memories
    if presentation is not None:
        data["presentation"] = presentation
    if personality is not None:
        data["personality"] = personality
    if user_context is not None:
        data["user_context"] = normalize_user_context(user_context)
    if chat_config is not None:
        existing_chat = data.get("chat") if isinstance(data.get("chat"), dict) else {}
        parsed_chat = parse_chat_config({**existing_chat, **chat_config})
        data["chat"] = {
            "return_greeting_enabled": parsed_chat.return_greeting_enabled,
            "return_greeting_idle_minutes": parsed_chat.return_greeting_idle_minutes,
            "return_greeting_phrases": list(parsed_chat.return_greeting_phrases),
            "max_tool_rounds": parsed_chat.max_tool_rounds,
        }
    CONFIG_PATH.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_provider_type(value: Any) -> str:
    provider_type = str(value or "none").strip() or "none"
    if provider_type not in PROVIDER_TYPES:
        raise ValueError("Provider type must be none, ollama, llama.cpp, openai, codex, or anthropic.")
    return provider_type


def provider_default_url(provider_type: str) -> str:
    return DEFAULT_PROVIDER_URLS.get(provider_type, "")


def provider_default_model(provider_type: str) -> str:
    return DEFAULT_PROVIDER_MODELS.get(provider_type, "")


def provider_secret_ref(provider_type: str) -> str:
    return f"provider:{provider_type}:api_key"


def none_provider() -> ProviderConfig:
    return ProviderConfig(type="none", url="", model="", key="none")


def parse_provider_entry(raw: Any) -> ProviderConfig:
    if not isinstance(raw, dict):
        raw = {}
    provider_type = normalize_provider_type(raw.get("type"))
    if provider_type == "none":
        return none_provider()

    url = str(raw.get("url") or provider_default_url(provider_type)).strip()
    model = str(raw.get("model") or provider_default_model(provider_type)).strip()
    key = str(raw.get("key") or provider_type).strip() or provider_type
    api_key_ref = str(raw.get("api_key_ref") or "").strip()
    if provider_type in CLOUD_PROVIDER_TYPES and not api_key_ref:
        api_key_ref = provider_secret_ref(provider_type)
    credentials = get_credentials(api_key_ref) if api_key_ref else {}
    api_key = str(raw.get("api_key") or credentials.get("api_key") or "").strip()
    return ProviderConfig(
        type=provider_type,
        url=url,
        model=model,
        embedding_model=str(raw.get("embedding_model") or "nomic-embed-text"),
        embedding_url=str(raw.get("embedding_url") or ""),
        native_tools=str(raw.get("native_tools") or "auto").strip().lower(),
        key=key,
        api_key=api_key,
        api_key_ref=api_key_ref,
        has_api_key=bool(api_key),
    )


def parse_provider_registry(raw: dict[str, Any]) -> tuple[ProviderConfig, tuple[ProviderConfig, ...], str]:
    raw_providers = raw.get("providers")
    providers: list[ProviderConfig] = []
    if isinstance(raw_providers, list):
        for entry in raw_providers:
            provider = parse_provider_entry(entry)
            if provider.type != "none" and provider.key not in {existing.key for existing in providers}:
                providers.append(provider)

    if not providers:
        legacy_provider = parse_provider_entry(raw.get("provider") if isinstance(raw.get("provider"), dict) else {})
        if legacy_provider.type != "none":
            providers.append(legacy_provider)

    active_provider = str(raw.get("active_provider") or "").strip()
    if not active_provider and isinstance(raw.get("provider"), dict):
        active_provider = str(raw["provider"].get("key") or raw["provider"].get("type") or "").strip()
    if not active_provider and providers:
        active_provider = providers[0].key
    active = next((provider for provider in providers if provider.key == active_provider), None)
    if active is None:
        active = providers[0] if providers else none_provider()
        active_provider = active.key
    return active, tuple(providers), active_provider or "none"


def provider_to_raw(provider: ProviderConfig) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "type": provider.type,
        "url": provider.url,
        "model": provider.model,
    }
    if provider.key and provider.key != provider.type:
        raw["key"] = provider.key
    if provider.embedding_model != "nomic-embed-text":
        raw["embedding_model"] = provider.embedding_model
    if provider.embedding_url:
        raw["embedding_url"] = provider.embedding_url
    if provider.native_tools != "auto":
        raw["native_tools"] = provider.native_tools
    if provider.api_key_ref:
        raw["api_key_ref"] = provider.api_key_ref
    return raw


def existing_provider_raw(raw: dict[str, Any], provider_type: str) -> dict[str, Any]:
    entries = raw.get("providers") if isinstance(raw.get("providers"), list) else []
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("type") or "") == provider_type:
            return entry
    legacy = raw.get("provider") if isinstance(raw.get("provider"), dict) else {}
    if str(legacy.get("type") or "") == provider_type:
        return legacy
    return {}


def provider_from_update(entry: dict[str, Any], existing_raw: dict[str, Any] | None = None) -> ProviderConfig:
    existing_raw = existing_raw or {}
    provider_type = normalize_provider_type(entry.get("type"))
    if provider_type == "none":
        return none_provider()
    url = str(entry.get("url") or provider_default_url(provider_type)).strip()
    model = str(entry.get("model") or provider_default_model(provider_type)).strip()
    if provider_type in URL_PROVIDER_TYPES and not url:
        raise ValueError("Provider URL is required unless provider type is none.")
    key = str(entry.get("key") or provider_type).strip() or provider_type
    api_key_ref = str(entry.get("api_key_ref") or existing_raw.get("api_key_ref") or "").strip()
    if provider_type in CLOUD_PROVIDER_TYPES:
        api_key_ref = api_key_ref or provider_secret_ref(provider_type)
        api_key = str(entry.get("api_key") or "").strip()
        existing_key = get_credentials(api_key_ref).get("api_key") if api_key_ref else ""
        if api_key:
            put_credentials(api_key_ref, {"api_key": api_key})
        elif not existing_key and not entry.get("has_api_key"):
            raise ValueError(f"{provider_type} API key is required.")
    else:
        api_key_ref = ""
    raw = {
        "type": provider_type,
        "url": url,
        "model": model,
        "key": key,
        "api_key_ref": api_key_ref,
        "embedding_model": str(entry.get("embedding_model") or existing_raw.get("embedding_model") or "nomic-embed-text"),
        "embedding_url": str(entry.get("embedding_url") or existing_raw.get("embedding_url") or ""),
        "native_tools": str(entry.get("native_tools") or existing_raw.get("native_tools") or "auto"),
    }
    return parse_provider_entry(raw)


def write_personality(name: str = "BitBuddy", personality: dict[str, Any] | None = None) -> None:
    # Legacy export helper retained for callers that explicitly ask for personality.yaml.
    write_legacy_personality_export(name, parse_personality_selection(personality))


def load_config() -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")
    seed_builtin_personality_files()
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    provider, providers, active_provider = parse_provider_registry(raw)
    memories = raw.get("memories") or {}
    chat = raw.get("chat") or {}
    autonomy = raw.get("autonomy") or {}
    dreaming = raw.get("dreaming") or {}
    calendar = raw.get("calendar") or {}
    email = raw.get("email") or {}
    mcp_servers = raw.get("mcp_servers") if "mcp_servers" in raw else {}
    if mcp_servers is None:
        mcp_servers = {}
    return BitBuddyConfig(
        name=str(raw.get("name") or "BitBuddy"),
        provider=provider,
        providers=providers,
        active_provider=active_provider,
        presentation=parse_presentation(raw.get("presentation")),
        personality=parse_personality_selection(raw.get("personality")),
        user_context=parse_user_context(raw.get("user_context")),
        chat=parse_chat_config(chat),
        autonomy=parse_autonomy_config(autonomy),
        dreaming=parse_dreaming_config(dreaming),
        calendar=parse_calendar_config(calendar),
        email=parse_email_config(email),
        mcp=parse_mcp_config(raw.get("mcp")),
        mcp_servers=parse_mcp_servers(mcp_servers),
        project_scan_interval_seconds=int(memories.get("project_scan_interval_seconds", 60)),
        idle_consolidation_enabled=bool(memories.get("idle_consolidation_enabled", True)),
        idle_consolidation_delay_seconds=float(memories.get("idle_consolidation_delay_seconds", 20)),
        idle_consolidation_recent_message_count=int(memories.get("idle_consolidation_recent_message_count", 30)),
        idle_consolidation_max_tool_rounds=int(memories.get("idle_consolidation_max_tool_rounds", 12)),
        idle_consolidation_max_actions=int(memories.get("idle_consolidation_max_actions", 8)),
    )


def parse_mcp_config(raw: Any) -> McpConfig:
    if not isinstance(raw, dict):
        raw = {}
    return McpConfig(enabled=bool(raw.get("enabled", False)))


def parse_mcp_servers(raw: Any) -> tuple[McpServerConfig, ...]:
    if not isinstance(raw, dict):
        return ()

    servers: list[McpServerConfig] = []
    for raw_name, raw_server in raw.items():
        name = normalize_mcp_server_name(str(raw_name or ""))
        if not name or not isinstance(raw_server, dict):
            continue
        command = str(raw_server.get("command") or "").strip()
        if not command:
            continue
        args_raw = raw_server.get("args")
        args = tuple(str(item) for item in args_raw if isinstance(item, (str, int, float))) if isinstance(args_raw, list) else ()
        env_raw = raw_server.get("env")
        env = {str(key): str(value) for key, value in env_raw.items()} if isinstance(env_raw, dict) else {}
        servers.append(
            McpServerConfig(
                name=name,
                command=command,
                args=args,
                env=env,
                timeout=max(1.0, float(raw_server.get("timeout") or 60)),
                connect_timeout=max(1.0, float(raw_server.get("connect_timeout") or 10)),
                enabled=bool(raw_server.get("enabled", True)),
            )
        )
    return tuple(servers)


def normalize_mcp_server_name(name: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or "").strip())
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean.strip("_")


def mcp_server_to_raw(server: McpServerConfig) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "command": server.command,
        "args": list(server.args),
        "timeout": server.timeout,
        "connect_timeout": server.connect_timeout,
        "enabled": server.enabled,
    }
    if server.env:
        raw["env"] = dict(server.env)
    return raw


def upsert_mcp_server(name: str, command: str, args: list[str] | tuple[str, ...] | None = None, *, timeout: float = 120, connect_timeout: float = 30, enabled: bool = True) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    servers = raw.get("mcp_servers") if isinstance(raw.get("mcp_servers"), dict) else {}
    clean_name = normalize_mcp_server_name(name)
    if not clean_name:
        raise ValueError("MCP server name is required.")
    clean_command = str(command or "").strip()
    if not clean_command:
        raise ValueError("MCP server command is required.")
    servers[clean_name] = {
        "command": clean_command,
        "args": [str(item) for item in (args or [])],
        "timeout": max(1.0, float(timeout)),
        "connect_timeout": max(1.0, float(connect_timeout)),
        "enabled": bool(enabled),
    }
    raw["mcp_servers"] = servers
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def update_mcp_config(update: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    existing = raw.get("mcp") if isinstance(raw.get("mcp"), dict) else {}
    existing["enabled"] = bool(update.get("enabled", existing.get("enabled", False)))
    raw["mcp"] = existing
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def parse_autonomy_config(raw: Any) -> AutonomyConfig:
    if not isinstance(raw, dict):
        raw = {}
    web_search = raw.get("web_search") if isinstance(raw.get("web_search"), dict) else {}
    max_results = int(web_search.get("max_results", 5)) if isinstance(web_search, dict) else 5
    idle_delay = float(raw.get("idle_delay_seconds", DEFAULT_AUTONOMY_IDLE_DELAY_SECONDS))
    return AutonomyConfig(
        enabled=bool(raw.get("enabled", True)),
        run_after_idle_consolidation=bool(raw.get("run_after_idle_consolidation", True)),
        idle_delay_seconds=idle_delay,
        repeat_idle_cycles=bool(raw.get("repeat_idle_cycles", True)),
        idle_backoff_multiplier=max(1.0, float(raw.get("idle_backoff_multiplier", DEFAULT_AUTONOMY_BACKOFF_MULTIPLIER))),
        idle_max_delay_seconds=max(idle_delay, float(raw.get("idle_max_delay_seconds", DEFAULT_AUTONOMY_MAX_DELAY_SECONDS))),
        max_actions_per_cycle=max(1, int(raw.get("max_actions_per_cycle", 1))),
        max_pending_questions=max(1, int(raw.get("max_pending_questions", 12))),
        max_pending_comments=max(1, int(raw.get("max_pending_comments", 12))),
        max_new_questions_per_cycle=max(0, int(raw.get("max_new_questions_per_cycle", 1))),
        max_autonomous_deliveries_per_day=max(1, int(raw.get("max_autonomous_deliveries_per_day", 10))),
        web_search=WebSearchConfig(
            enabled=bool(web_search.get("enabled", True)),
            provider=str(web_search.get("provider") or "searxng"),
            url=str(web_search.get("url") or "http://127.0.0.1:8888"),
            startup_command=str(web_search.get("startup_command") or "managed"),
            max_results=max(1, min(10, max_results)),
        ),
    )


def parse_calendar_config(raw: Any) -> CalendarConfig:
    if not isinstance(raw, dict):
        raw = {}
    return CalendarConfig(
        enabled=bool(raw.get("enabled", False)),
        default_provider=str(raw.get("default_provider") or "local"),
        reminder_upcoming_minutes=max(1, int(raw.get("reminder_upcoming_minutes", 60))),
        reminder_starting_soon_minutes=max(1, int(raw.get("reminder_starting_soon_minutes", 15))),
        urgent_interrupts_enabled=bool(raw.get("urgent_interrupts_enabled", True)),
        urgent_interrupt_persistent=bool(raw.get("urgent_interrupt_persistent", True)),
        conflict_warnings_enabled=bool(raw.get("conflict_warnings_enabled", True)),
        free_day_summary_enabled=bool(raw.get("free_day_summary_enabled", True)),
        chat_nudges_enabled=bool(raw.get("chat_nudges_enabled", True)),
        scheduler_tick_seconds=max(15, int(raw.get("scheduler_tick_seconds", 60))),
        holidays_enabled=bool(raw.get("holidays_enabled", True)),
        holidays_country=str(raw.get("holidays_country") or "").strip().upper(),
    )


def parse_email_config(raw: Any) -> EmailConfig:
    if not isinstance(raw, dict):
        raw = {}
    try:
        port = int(raw.get("imap_port", 993))
    except (TypeError, ValueError):
        port = 993
    try:
        max_preview = int(raw.get("max_preview_messages", 50))
    except (TypeError, ValueError):
        max_preview = 50
    security = str(raw.get("imap_security") or "ssl").strip().lower()
    if security not in {"ssl", "starttls", "none"}:
        security = "ssl"
    provider = str(raw.get("provider") or "imap").strip().lower()
    if provider not in {"imap", "gmail", "outlook"}:
        provider = "imap"
    return EmailConfig(
        enabled=bool(raw.get("enabled", False)),
        provider=provider,
        account_label=str(raw.get("account_label") or "").strip(),
        email_address=str(raw.get("email_address") or "").strip(),
        imap_host=str(raw.get("imap_host") or "").strip(),
        imap_port=max(1, min(65535, port)),
        imap_security=security,
        username=str(raw.get("username") or "").strip(),
        credentials_ref=str(raw.get("credentials_ref") or "").strip(),
        gmail_client_id=str(raw.get("gmail_client_id") or "").strip(),
        gmail_credentials_ref=str(raw.get("gmail_credentials_ref") or "").strip(),
        gmail_token_ref=str(raw.get("gmail_token_ref") or "").strip(),
        gmail_redirect_uri=str(raw.get("gmail_redirect_uri") or "http://localhost:8787/email/gmail/callback").strip() or "http://localhost:8787/email/gmail/callback",
        default_mailbox=str(raw.get("default_mailbox") or "INBOX").strip() or "INBOX",
        max_preview_messages=max(1, min(200, max_preview)),
    )


def update_email_config(email: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("email") if isinstance(raw.get("email"), dict) else {}
    next_raw = {**existing}
    for key in (
        "enabled",
        "provider",
        "account_label",
        "email_address",
        "imap_host",
        "imap_port",
        "imap_security",
        "username",
        "credentials_ref",
        "gmail_client_id",
        "gmail_credentials_ref",
        "gmail_token_ref",
        "gmail_redirect_uri",
        "default_mailbox",
        "max_preview_messages",
    ):
        if key in email:
            next_raw[key] = email[key]

    parsed = parse_email_config(next_raw)
    raw["email"] = {
        "enabled": parsed.enabled,
        "provider": parsed.provider,
        "account_label": parsed.account_label,
        "email_address": parsed.email_address,
        "imap_host": parsed.imap_host,
        "imap_port": parsed.imap_port,
        "imap_security": parsed.imap_security,
        "username": parsed.username,
        "credentials_ref": parsed.credentials_ref,
        "gmail_client_id": parsed.gmail_client_id,
        "gmail_credentials_ref": parsed.gmail_credentials_ref,
        "gmail_token_ref": parsed.gmail_token_ref,
        "gmail_redirect_uri": parsed.gmail_redirect_uri,
        "default_mailbox": parsed.default_mailbox,
        "max_preview_messages": parsed.max_preview_messages,
    }
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def update_calendar_config(calendar: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("calendar") if isinstance(raw.get("calendar"), dict) else {}
    next_raw = {**existing}
    for key in (
        "enabled",
        "default_provider",
        "reminder_upcoming_minutes",
        "reminder_starting_soon_minutes",
        "urgent_interrupts_enabled",
        "urgent_interrupt_persistent",
        "conflict_warnings_enabled",
        "free_day_summary_enabled",
        "chat_nudges_enabled",
        "scheduler_tick_seconds",
        "holidays_enabled",
        "holidays_country",
    ):
        if key in calendar:
            next_raw[key] = calendar[key]

    parsed = parse_calendar_config(next_raw)
    raw["calendar"] = {
        "enabled": parsed.enabled,
        "default_provider": parsed.default_provider,
        "reminder_upcoming_minutes": parsed.reminder_upcoming_minutes,
        "reminder_starting_soon_minutes": parsed.reminder_starting_soon_minutes,
        "urgent_interrupts_enabled": parsed.urgent_interrupts_enabled,
        "urgent_interrupt_persistent": parsed.urgent_interrupt_persistent,
        "conflict_warnings_enabled": parsed.conflict_warnings_enabled,
        "free_day_summary_enabled": parsed.free_day_summary_enabled,
        "chat_nudges_enabled": parsed.chat_nudges_enabled,
        "scheduler_tick_seconds": parsed.scheduler_tick_seconds,
        "holidays_enabled": parsed.holidays_enabled,
        "holidays_country": parsed.holidays_country,
    }
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def normalize_reasoning_budget(value: Any) -> int:
    """Reasoning token budget for thinking turns: -1 means unlimited, >= 0 caps it."""
    try:
        budget = int(value)
    except (TypeError, ValueError):
        return -1
    if budget < 0:
        return -1
    return budget


def parse_chat_config(raw: Any) -> ChatConfig:
    if not isinstance(raw, dict):
        raw = {}
    return ChatConfig(
        return_greeting_enabled=bool(raw.get("return_greeting_enabled", True)),
        return_greeting_idle_minutes=max(1, int(raw.get("return_greeting_idle_minutes", 60))),
        return_greeting_phrases=tuple(clean_phrase_list(raw.get("return_greeting_phrases"), ["Hey, welcome back.", "Hi, welcome back."])),
        max_tool_rounds=max(1, int(raw.get("max_tool_rounds", 99))),
        reasoning_budget_tokens=normalize_reasoning_budget(raw.get("reasoning_budget_tokens", -1)),
    )


def update_chat_config(chat: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("chat") if isinstance(raw.get("chat"), dict) else {}
    next_raw = {**existing}
    for key in (
        "return_greeting_enabled",
        "return_greeting_idle_minutes",
        "return_greeting_phrases",
        "max_tool_rounds",
        "reasoning_budget_tokens",
    ):
        if key in chat:
            next_raw[key] = chat[key]

    parsed = parse_chat_config(next_raw)
    raw["chat"] = {
        "return_greeting_enabled": parsed.return_greeting_enabled,
        "return_greeting_idle_minutes": parsed.return_greeting_idle_minutes,
        "return_greeting_phrases": list(parsed.return_greeting_phrases),
        "max_tool_rounds": parsed.max_tool_rounds,
        "reasoning_budget_tokens": parsed.reasoning_budget_tokens,
    }
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def parse_dreaming_config(raw: Any) -> DreamingConfig:
    if not isinstance(raw, dict):
        raw = {}
    return DreamingConfig(
        enabled=bool(raw.get("enabled", True)),
        bedtime=normalize_hhmm(str(raw.get("bedtime") or DEFAULT_DREAMING_BEDTIME), DEFAULT_DREAMING_BEDTIME),
        wake_time=normalize_hhmm(str(raw.get("wake_time") or DEFAULT_DREAMING_WAKE_TIME), DEFAULT_DREAMING_WAKE_TIME),
        goodnight_triggers=tuple(clean_string_list(raw.get("goodnight_triggers"), ["goodnight", "good night"])),
        goodmorning_triggers=tuple(clean_string_list(raw.get("goodmorning_triggers"), ["good morning", "morning"])),
        idle_before_dream_minutes=max(0, int(raw.get("idle_before_dream_minutes", 30))),
        minimum_dream_window_minutes=max(0, int(raw.get("minimum_dream_window_minutes", 45))),
        max_dream_tasks_per_night=max(1, int(raw.get("max_dream_tasks_per_night", 3))),
        allow_post_dream_autonomy_rounds=max(0, int(raw.get("allow_post_dream_autonomy_rounds", 0))),
        soft_delete_memories=bool(raw.get("soft_delete_memories", True)),
        quiet_mode_after_bedtime=bool(raw.get("quiet_mode_after_bedtime", True)),
        goodnight_immediate_winddown=bool(raw.get("goodnight_immediate_winddown", False)),
        stale_intention_days=max(1, int(raw.get("stale_intention_days", 14))),
        low_priority_stale_intention_days=max(1, int(raw.get("low_priority_stale_intention_days", 7))),
        self_note_injection_enabled=bool(raw.get("self_note_injection_enabled", False)),
    )


def normalize_hhmm(value: str, fallback: str) -> str:
    parts = value.strip().split(":")
    if len(parts) != 2:
        return fallback
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return fallback
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback
    return f"{hour:02d}:{minute:02d}"


def clean_string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        value = fallback
    result = []
    for item in value:
        clean = str(item or "").strip().lower()
        if clean and clean not in result:
            result.append(clean)
    return result or fallback


def clean_phrase_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        value = fallback
    result = []
    for item in value:
        clean = str(item or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result or fallback


def parse_user_context(raw: Any) -> UserContextConfig:
    if not isinstance(raw, dict):
        raw = {}

    try:
        normalized = normalize_user_context(raw)
    except ValueError:
        normalized = normalize_user_context({})

    return UserContextConfig(
        location_label=normalized["location_label"],
        timezone=normalized["timezone"],
        locale=normalized["locale"],
    )


def normalize_user_context(raw: dict[str, Any]) -> dict[str, str]:
    timezone = str(raw.get("timezone") or "UTC").strip() or "UTC"
    validate_timezone(timezone)

    return {
        "location_label": str(raw.get("location_label") or "").strip(),
        "timezone": timezone,
        "locale": str(raw.get("locale") or "en-US").strip() or "en-US",
    }


def validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown timezone: {timezone}") from error


def update_user_context(user_context: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    raw["user_context"] = normalize_user_context(user_context)
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    return load_config()


def update_model_runtime_config(update: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    if isinstance(update.get("providers"), list):
        old_provider_refs = {
            str(entry.get("type")): str(entry.get("api_key_ref") or provider_secret_ref(str(entry.get("type"))))
            for entry in (raw.get("providers") if isinstance(raw.get("providers"), list) else [])
            if isinstance(entry, dict) and str(entry.get("type") or "") in CLOUD_PROVIDER_TYPES
        }
        providers: list[ProviderConfig] = []
        seen: set[str] = set()
        for entry in update["providers"]:
            if not isinstance(entry, dict):
                continue
            provider_type = normalize_provider_type(entry.get("type"))
            if provider_type == "none" or provider_type in seen:
                continue
            provider = provider_from_update(entry, existing_provider_raw(raw, provider_type))
            providers.append(provider)
            seen.add(provider_type)
        active_provider = str(update.get("active_provider") or raw.get("active_provider") or "").strip()
        if active_provider not in {provider.key for provider in providers}:
            active_provider = providers[0].key if providers else "none"
        active = next((provider for provider in providers if provider.key == active_provider), none_provider())
        kept_cloud_types = {provider.type for provider in providers if provider.type in CLOUD_PROVIDER_TYPES}
        for provider_type, ref in old_provider_refs.items():
            if provider_type not in kept_cloud_types:
                delete_credentials(ref)
        raw["providers"] = [provider_to_raw(provider) for provider in providers]
        raw["active_provider"] = active_provider
        raw["provider"] = provider_to_raw(active) if active.type != "none" else {"type": "none", "url": "", "model": ""}
    else:
        provider = update.get("provider") if isinstance(update.get("provider"), dict) else {}
        next_provider = provider_from_update(provider, existing_provider_raw(raw, str(provider.get("type") or "none")))
        providers = [] if next_provider.type == "none" else [next_provider]
        raw["providers"] = [provider_to_raw(provider) for provider in providers]
        raw["active_provider"] = next_provider.key
        raw["provider"] = provider_to_raw(next_provider) if next_provider.type != "none" else {"type": "none", "url": "", "model": ""}

    memories = raw.get("memories") if isinstance(raw.get("memories"), dict) else {}
    if "project_scan_interval_seconds" in update:
        memories["project_scan_interval_seconds"] = max(0, int(update.get("project_scan_interval_seconds") or 0))
    raw["memories"] = memories

    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def update_personality_config(personality: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("personality") if isinstance(raw.get("personality"), dict) else {}
    next_raw = {**existing}
    for key in (
        "source",
        "id",
        "path",
        "expressiveness",
        "proactivity",
        "quirk_frequency",
        "bitbuddy_likes",
        "bitbuddy_dislikes",
    ):
        if key in personality:
            next_raw[key] = personality[key]

    parsed = parse_personality_selection(next_raw)
    raw["personality"] = {
        "source": parsed.source,
        "id": parsed.id,
        "path": parsed.path,
        "expressiveness": parsed.expressiveness,
        "proactivity": parsed.proactivity,
        "quirk_frequency": parsed.quirk_frequency,
        "bitbuddy_likes": list(parsed.bitbuddy_likes),
        "bitbuddy_dislikes": list(parsed.bitbuddy_dislikes),
    }
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def update_autonomy_config(autonomy: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("autonomy") if isinstance(raw.get("autonomy"), dict) else {}
    next_raw = {**existing}
    for key in (
        "enabled",
        "run_after_idle_consolidation",
        "idle_delay_seconds",
        "repeat_idle_cycles",
        "idle_backoff_multiplier",
        "idle_max_delay_seconds",
        "max_actions_per_cycle",
        "max_pending_questions",
        "max_pending_comments",
        "max_new_questions_per_cycle",
        "max_autonomous_deliveries_per_day",
    ):
        if key in autonomy:
            next_raw[key] = autonomy[key]

    existing_web_search = existing.get("web_search") if isinstance(existing.get("web_search"), dict) else {}
    web_search = autonomy.get("web_search") if isinstance(autonomy.get("web_search"), dict) else {}
    if web_search:
        next_raw["web_search"] = {**existing_web_search, **web_search}

    parsed = parse_autonomy_config(next_raw)
    raw["autonomy"] = {
        "enabled": parsed.enabled,
        "run_after_idle_consolidation": parsed.run_after_idle_consolidation,
        "idle_delay_seconds": parsed.idle_delay_seconds,
        "repeat_idle_cycles": parsed.repeat_idle_cycles,
        "idle_backoff_multiplier": parsed.idle_backoff_multiplier,
        "idle_max_delay_seconds": parsed.idle_max_delay_seconds,
        "max_actions_per_cycle": parsed.max_actions_per_cycle,
        "max_pending_questions": parsed.max_pending_questions,
        "max_pending_comments": parsed.max_pending_comments,
        "max_new_questions_per_cycle": parsed.max_new_questions_per_cycle,
        "max_autonomous_deliveries_per_day": parsed.max_autonomous_deliveries_per_day,
        "web_search": {
            "enabled": parsed.web_search.enabled,
            "provider": parsed.web_search.provider,
            "url": parsed.web_search.url,
            "startup_command": parsed.web_search.startup_command,
            "max_results": parsed.web_search.max_results,
        },
    }
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config()


def update_dreaming_config(dreaming: dict[str, Any]) -> BitBuddyConfig:
    if not CONFIG_PATH.exists():
        write_config("none", "", "")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("dreaming") if isinstance(raw.get("dreaming"), dict) else {}
    next_raw = {**existing}
    for key in (
        "enabled",
        "bedtime",
        "wake_time",
        "goodnight_triggers",
        "goodmorning_triggers",
        "idle_before_dream_minutes",
        "minimum_dream_window_minutes",
        "max_dream_tasks_per_night",
        "allow_post_dream_autonomy_rounds",
        "soft_delete_memories",
        "quiet_mode_after_bedtime",
        "goodnight_immediate_winddown",
        "stale_intention_days",
        "low_priority_stale_intention_days",
        "self_note_injection_enabled",
    ):
        if key in dreaming:
            next_raw[key] = dreaming[key]

    parsed = parse_dreaming_config(next_raw)
    raw["dreaming"] = {
        "enabled": parsed.enabled,
        "bedtime": parsed.bedtime,
        "wake_time": parsed.wake_time,
        "goodnight_triggers": list(parsed.goodnight_triggers),
        "goodmorning_triggers": list(parsed.goodmorning_triggers),
        "idle_before_dream_minutes": parsed.idle_before_dream_minutes,
        "minimum_dream_window_minutes": parsed.minimum_dream_window_minutes,
        "max_dream_tasks_per_night": parsed.max_dream_tasks_per_night,
        "allow_post_dream_autonomy_rounds": parsed.allow_post_dream_autonomy_rounds,
        "soft_delete_memories": parsed.soft_delete_memories,
        "quiet_mode_after_bedtime": parsed.quiet_mode_after_bedtime,
        "goodnight_immediate_winddown": parsed.goodnight_immediate_winddown,
        "stale_intention_days": parsed.stale_intention_days,
        "low_priority_stale_intention_days": parsed.low_priority_stale_intention_days,
        "self_note_injection_enabled": parsed.self_note_injection_enabled,
    }
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    return load_config()


def load_personality() -> dict[str, Any]:
    if PERSONALITY_PATH.exists():
        return yaml.safe_load(PERSONALITY_PATH.read_text(encoding="utf-8")) or DEFAULT_PERSONALITY

    config = load_config()
    profile = load_selected_personality(config.personality)
    return selected_personality_to_legacy_dict(config.name, profile)
