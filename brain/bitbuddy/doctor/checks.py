from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import socket
import sqlite3
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..auth import api_token_path
from ..calendar.secrets import SECRETS_PATH
from ..config import CLOUD_PROVIDER_TYPES, URL_PROVIDER_TYPES, parse_autonomy_config, parse_calendar_config, parse_dreaming_config, parse_provider_registry, parse_user_context
from ..paths import APP_DIR, ARTIFACTS_DIR, CONFIG_PATH, GLOBAL_DB_PATH, PROJECTS_DIR, SKILLS_DIR, WEB_DIR, WORKSPACE_DIR
from .report import DoctorCheckResult


BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8787
WEB_HOST = "127.0.0.1"
WEB_PORT = 5173


@dataclass(frozen=True)
class DoctorContext:
    raw_config: dict[str, Any] | None = None
    config_error: str = ""
    provider: Any | None = None
    providers: tuple[Any, ...] = ()
    active_provider: str = "none"
    autonomy: Any | None = None
    dreaming: Any | None = None
    calendar: Any | None = None
    web_search_ok: bool | None = None


EXPECTED_TABLES = {
    "activity": "db.init",
    "chats": "db.init",
    "chat_messages": "db.init",
    "memories": "db.init",
    "intentions": "db.init",
    "lifecycle_state": "db.init",
    "workspace_documents": "db.init",
    "notifications": "db.init",
    "dream_runs": "db.init",
    "dream_tasks": "db.init",
    "self_state": "db.init",
    "goals": "db.init",
    "personality_evolution": "db.init",
}


def run_doctor_checks() -> list[DoctorCheckResult]:
    results: list[DoctorCheckResult] = []
    context, config_results = load_config_context_readonly()
    results.extend(system_checks())
    results.extend(config_results)
    results.extend(config_checks(context))
    results.extend(storage_checks())
    results.extend(database_checks())
    results.extend(runtime_checks())
    web_results, web_search_ok = web_search_checks(context)
    results.extend(web_results)
    context = DoctorContext(**{**context.__dict__, "web_search_ok": web_search_ok})
    results.extend(autonomy_checks(context))
    results.extend(safety_checks())
    return results


def system_checks() -> list[DoctorCheckResult]:
    results = [
        DoctorCheckResult(
            "system.python",
            "System",
            "pass" if sys.version_info >= (3, 11) else "fail",
            "Python version OK" if sys.version_info >= (3, 11) else "Python version unsupported",
            f"Running Python {platform.python_version()}; BitBuddy requires >= 3.11.",
        ),
        DoctorCheckResult("system.platform", "System", "pass", f"Platform detected: {platform.system() or 'unknown'}", platform.platform()),
    ]
    for package in ("yaml", "questionary", "holidays", "sqlite3"):
        results.append(
            DoctorCheckResult(
                f"system.import.{package}",
                "System",
                "pass" if importlib.util.find_spec(package) else "fail",
                f"Python package available: {package}" if importlib.util.find_spec(package) else f"Missing Python package: {package}",
                "Install BitBuddy with `pip install -e .`." if not importlib.util.find_spec(package) else "",
            )
        )
    node = shutil.which("node")
    npm = shutil.which("npm")
    results.append(DoctorCheckResult("system.node", "System", "pass" if node else "fail", "Node found" if node else "Node not found", node or "Install Node.js before running the web UI."))
    results.append(DoctorCheckResult("system.npm", "System", "pass" if npm else "fail", "npm found" if npm else "npm not found", npm or "Install npm before running the web UI."))
    package_json = WEB_DIR / "package.json"
    results.append(DoctorCheckResult("system.web_package", "System", "pass" if package_json.is_file() else "fail", "Web package manifest found" if package_json.is_file() else "Web package manifest missing", str(package_json)))
    node_modules = WEB_DIR / "node_modules"
    results.append(DoctorCheckResult("system.web_deps", "System", "pass" if node_modules.is_dir() else "fail", "Web dependencies installed" if node_modules.is_dir() else "npm dependencies missing", "" if node_modules.is_dir() else "Run `cd web && npm install`, or use `bitbuddy doctor fix`.", "web.npm_install" if not node_modules.is_dir() else None))
    shell = os.environ.get("SHELL") or os.environ.get("COMSPEC") or ""
    results.append(DoctorCheckResult("system.shell", "System", "pass" if shell else "warn", "Shell environment detected" if shell else "Shell environment not detected", shell or "This is usually harmless unless subprocess commands fail."))
    return results


def load_config_context_readonly() -> tuple[DoctorContext, list[DoctorCheckResult]]:
    if not CONFIG_PATH.exists():
        return DoctorContext(config_error="missing"), [DoctorCheckResult("config.exists", "Config", "fail", "Config file missing", str(CONFIG_PATH), "config.create_default")]
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as error:
        return DoctorContext(config_error=str(error)), [DoctorCheckResult("config.parse", "Config", "fail", "Config file could not be parsed", str(error), "config.reset_default")]
    if not isinstance(raw, dict):
        return DoctorContext(config_error="Config root is not an object."), [DoctorCheckResult("config.parse", "Config", "fail", "Config file is not a YAML object", str(CONFIG_PATH), "config.reset_default")]
    try:
        provider, providers, active_provider = parse_provider_registry(raw)
        context = DoctorContext(
            raw_config=raw,
            provider=provider,
            providers=providers,
            active_provider=active_provider,
            autonomy=parse_autonomy_config(raw.get("autonomy")),
            dreaming=parse_dreaming_config(raw.get("dreaming")),
            calendar=parse_calendar_config(raw.get("calendar")),
        )
    except Exception as error:
        return DoctorContext(raw_config=raw, config_error=str(error)), [DoctorCheckResult("config.parse", "Config", "fail", "Config values could not be parsed", str(error), "config.reset_default")]
    return context, [DoctorCheckResult("config.exists", "Config", "pass", "Config file found", str(CONFIG_PATH)), DoctorCheckResult("config.parse", "Config", "pass", "Config loads successfully")]


def config_checks(context: DoctorContext) -> list[DoctorCheckResult]:
    if context.raw_config is None or context.provider is None:
        return []
    results: list[DoctorCheckResult] = []
    provider = context.provider
    provider_count = len(context.providers)
    results.append(DoctorCheckResult("config.provider_registry", "Config", "pass" if provider_count else "warn", "Provider registry loaded" if provider_count else "No providers saved", f"{provider_count} provider(s) configured."))
    results.append(DoctorCheckResult("config.provider", "Config", "pass" if provider.type != "none" else "fail", "Model provider configured" if provider.type != "none" else "No model provider configured", f"Active provider: {provider.type}" if provider.type != "none" else "Run `bitbuddy setup` to configure a provider."))
    if provider.type in URL_PROVIDER_TYPES:
        results.append(DoctorCheckResult("config.provider_url", "Config", "pass" if provider.url else "fail", "Provider URL configured" if provider.url else "Provider URL missing", provider.url or "Save a URL in Settings or rerun `bitbuddy setup`."))
    if provider.type in CLOUD_PROVIDER_TYPES:
        results.append(DoctorCheckResult("config.provider_key", "Config", "pass" if provider.api_key else "fail", f"{provider.type} API key configured" if provider.api_key else f"{provider.type} API key missing", "Secrets are stored outside config.yaml." if provider.api_key else "Reconnect this provider in Settings."))
    try:
        parse_user_context(context.raw_config.get("user_context"))
        results.append(DoctorCheckResult("config.timezone", "Config", "pass", "User timezone valid"))
    except Exception as error:
        results.append(DoctorCheckResult("config.timezone", "Config", "warn", "User timezone invalid", str(error)))
    if context.autonomy:
        results.append(DoctorCheckResult("config.autonomy", "Config", "pass", "Autonomy settings parsed"))
        if context.autonomy.idle_delay_seconds < 0 or context.autonomy.max_autonomous_deliveries_per_day < 1:
            results.append(DoctorCheckResult("config.autonomy_sane", "Config", "fail", "Autonomy settings are invalid", "Delay must be non-negative and delivery cap must be positive.", "config.clamp_safe"))
    if context.dreaming:
        ok = bool(context.dreaming.bedtime and context.dreaming.wake_time and context.dreaming.idle_before_dream_minutes > 0)
        results.append(DoctorCheckResult("config.dreaming_sane", "Config", "pass" if ok else "warn", "Dreaming settings sane" if ok else "Dreaming settings look unusual", "Bedtime/wake and idle-before-dream are checked."))
    if context.calendar and context.calendar.enabled:
        results.append(DoctorCheckResult("config.calendar", "Config", "pass", "Calendar config enabled and parsed"))
    return results


def storage_checks() -> list[DoctorCheckResult]:
    paths = [
        ("storage.app", APP_DIR, "BitBuddy config directory", "dirs.ensure"),
        ("storage.workspace", WORKSPACE_DIR, "Workspace directory", "dirs.ensure"),
        ("storage.artifacts", ARTIFACTS_DIR, "Artifacts directory", "dirs.ensure"),
        ("storage.projects", PROJECTS_DIR, "Projects directory", "dirs.ensure"),
        ("storage.skills", SKILLS_DIR, "Skills directory", "dirs.ensure"),
        ("storage.tools", APP_DIR / "tools" / "bin", "Managed tools bin directory", "dirs.ensure"),
    ]
    results: list[DoctorCheckResult] = []
    app_parent = APP_DIR.parent
    results.append(DoctorCheckResult("storage.parent_writable", "Storage", "pass" if os.access(app_parent, os.W_OK) else "fail", "BitBuddy parent directory writable" if os.access(app_parent, os.W_OK) else "BitBuddy parent directory not writable", str(app_parent)))
    for check_id, path, title, fix_id in paths:
        exists = path.is_dir()
        writable = exists and os.access(path, os.W_OK)
        status = "pass" if writable else "fail"
        results.append(DoctorCheckResult(check_id, "Storage", status, f"{title} writable" if writable else f"{title} missing or not writable", str(path), None if writable else fix_id))
    results.extend(storage_permission_checks())
    db_parent = GLOBAL_DB_PATH.parent
    results.append(DoctorCheckResult("storage.db_parent", "Storage", "pass" if os.access(db_parent, os.W_OK) else "fail", "Database parent writable" if os.access(db_parent, os.W_OK) else "Database parent not writable", str(db_parent), None if os.access(db_parent, os.W_OK) else "dirs.ensure"))
    return results


def storage_permission_checks() -> list[DoctorCheckResult]:
    checks = [
        ("storage.perms.config", CONFIG_PATH, "Config file"),
        ("storage.perms.db", GLOBAL_DB_PATH, "SQLite database"),
        ("storage.perms.secrets", SECRETS_PATH, "Credential store"),
        ("storage.perms.api_token", api_token_path(), "API token"),
    ]
    results: list[DoctorCheckResult] = []
    if APP_DIR.exists():
        results.append(permission_result("storage.perms.app", APP_DIR, "BitBuddy home directory", directory=True))
    for check_id, path, label in checks:
        if path.exists():
            results.append(permission_result(check_id, path, label))
    return results


def permission_result(check_id: str, path: Path, label: str, *, directory: bool = False) -> DoctorCheckResult:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as error:
        return DoctorCheckResult(check_id, "Storage", "warn", f"Could not inspect {label} permissions", str(error))
    unsafe_bits = 0o077 if not directory else 0o027
    safe = (mode & unsafe_bits) == 0
    expected = "0600" if not directory else "0750 or stricter"
    return DoctorCheckResult(
        check_id,
        "Storage",
        "pass" if safe else "warn",
        f"{label} permissions look private" if safe else f"{label} is readable/writable by other users",
        f"{path} mode={mode:03o}; expected {expected}.",
    )


def database_checks() -> list[DoctorCheckResult]:
    if not GLOBAL_DB_PATH.exists():
        return [DoctorCheckResult("db.exists", "Database", "fail", "SQLite database missing", str(GLOBAL_DB_PATH), "db.init")]
    results = [DoctorCheckResult("db.exists", "Database", "pass", "SQLite database found", str(GLOBAL_DB_PATH))]
    try:
        connection = sqlite3.connect(f"file:{GLOBAL_DB_PATH}?mode=rw", uri=True)
        try:
            connection.execute("pragma query_only = on")
            quick = connection.execute("pragma quick_check").fetchone()
            ok = quick and str(quick[0]).lower() == "ok"
            results.append(DoctorCheckResult("db.quick_check", "Database", "pass" if ok else "fail", "SQLite quick_check passed" if ok else "SQLite quick_check failed", str(quick[0] if quick else "no result")))
            table_rows = connection.execute("select name from sqlite_master where type = 'table'").fetchall()
            tables = {str(row[0]) for row in table_rows}
            for table, fix_id in EXPECTED_TABLES.items():
                results.append(DoctorCheckResult(f"db.table.{table}", "Database", "pass" if table in tables else "warn", f"Table present: {table}" if table in tables else f"Missing table: {table}", "" if table in tables else "Missing tables can be initialized safely.", None if table in tables else fix_id))
            writable = os.access(GLOBAL_DB_PATH, os.W_OK)
            results.append(DoctorCheckResult("db.file_writable", "Database", "pass" if writable else "fail", "Database file appears writable" if writable else "Database file is not writable", "Checked filesystem permissions without writing."))
        finally:
            connection.close()
    except sqlite3.Error as error:
        results.append(DoctorCheckResult("db.open", "Database", "fail", "SQLite database could not be opened", str(error), "db.init"))
    return results


def runtime_checks() -> list[DoctorCheckResult]:
    results: list[DoctorCheckResult] = []
    backend_open = port_is_open(BACKEND_HOST, BACKEND_PORT)
    if backend_open:
        ok, detail = http_json_ok(f"http://{BACKEND_HOST}:{BACKEND_PORT}/health")
        results.append(DoctorCheckResult("runtime.backend", "Services", "pass" if ok else "warn", "Backend is running" if ok else "Backend port occupied by unknown service", detail))
    else:
        results.append(DoctorCheckResult("runtime.backend_port", "Services", "pass", "Backend port available", f"{BACKEND_HOST}:{BACKEND_PORT}"))
    web_open = port_is_open(WEB_HOST, WEB_PORT)
    if web_open:
        ok, detail = http_text_ok(f"http://{WEB_HOST}:{WEB_PORT}/")
        results.append(DoctorCheckResult("runtime.web", "Services", "pass" if ok else "warn", "Web UI responds locally" if ok else "Web UI port occupied by unknown service", detail))
    else:
        results.append(DoctorCheckResult("runtime.web_port", "Services", "pass", "Web UI port available", f"{WEB_HOST}:{WEB_PORT}"))
    return results


def web_search_checks(context: DoctorContext) -> tuple[list[DoctorCheckResult], bool | None]:
    autonomy = context.autonomy
    if autonomy is None or not autonomy.web_search.enabled:
        return [DoctorCheckResult("web_search.enabled", "Web Search", "skip", "Web search disabled")], None
    config = autonomy.web_search
    parsed = urllib.parse.urlparse(config.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return [DoctorCheckResult("web_search.url", "Web Search", "fail", "Web search URL invalid", config.url, "web_search.reset_defaults")], False
    results = [DoctorCheckResult("web_search.url", "Web Search", "pass", "Web search URL valid", config.url)]
    status_ok, status_detail = http_json_ok(f"{config.url.rstrip('/')}/status")
    if not status_ok:
        base_ok, base_detail = http_text_ok(config.url)
        status_ok = base_ok
        status_detail = base_detail
    results.append(DoctorCheckResult("web_search.reachable", "Web Search", "pass" if status_ok else "warn", "SearxNG-compatible backend reachable" if status_ok else "SearxNG-compatible backend unreachable", status_detail))
    if status_ok:
        search_ok, search_detail = http_search_results_ok(f"{config.url.rstrip('/')}/search?q=weather+Halifax+Nova+Scotia&format=json&categories=general")
        results.append(DoctorCheckResult("web_search.search", "Web Search", "pass" if search_ok else "warn", "Basic web search returned results" if search_ok else "Basic web search returned no usable results", search_detail))
    command = config.startup_command.strip()
    if command.lower() in {"", "managed", "builtin", "bitbuddy", "searxng"}:
        results.append(DoctorCheckResult("web_search.startup", "Web Search", "pass", "Managed web search backend configured"))
    else:
        executable = shutil.which(command.split()[0]) if command else None
        results.append(DoctorCheckResult("web_search.startup", "Web Search", "pass" if executable else "warn", "Custom web search startup command found" if executable else "Custom web search startup command not found", command))
    return results, status_ok


def autonomy_checks(context: DoctorContext) -> list[DoctorCheckResult]:
    if context.autonomy is None:
        return []
    autonomy = context.autonomy
    results = [DoctorCheckResult("autonomy.enabled", "Autonomy", "pass" if autonomy.enabled else "skip", "Autonomy enabled" if autonomy.enabled else "Autonomy disabled")]
    if autonomy.enabled and context.provider is not None and context.provider.type == "none":
        results.append(DoctorCheckResult("autonomy.provider", "Autonomy", "warn", "Autonomy enabled without model provider", "Idle autonomy cannot run useful model-backed cycles until a provider is configured."))
    if autonomy.enabled and autonomy.web_search.enabled and context.web_search_ok is False:
        results.append(DoctorCheckResult("autonomy.web_curiosity", "Autonomy", "warn", "Web curiosity enabled but web search is broken", "Autonomy can still run other safe activities."))
    if autonomy.repeat_idle_cycles and autonomy.idle_delay_seconds < 60:
        results.append(DoctorCheckResult("autonomy.usage", "Autonomy", "warn", "High background usage settings detected", "Repeat cycles with a short idle delay may consume paid provider usage."))
    workspace_ok = WORKSPACE_DIR.is_dir() and os.access(WORKSPACE_DIR, os.W_OK)
    results.append(DoctorCheckResult("autonomy.workspace", "Autonomy", "pass" if workspace_ok else "fail", "Autonomy workspace writable" if workspace_ok else "Autonomy workspace missing or not writable", str(WORKSPACE_DIR), None if workspace_ok else "dirs.ensure"))
    results.append(DoctorCheckResult("autonomy.project_mutation", "Autonomy", "pass", "Autonomy project mutation disabled", "Autonomy writes BitBuddy-owned memory/workspace notes, not user project files."))
    return results


def safety_checks() -> list[DoctorCheckResult]:
    results = []
    for check_id, path, title in (("safety.workspace_scope", WORKSPACE_DIR, "Workspace confined to ~/.bitbuddy"), ("safety.artifacts_scope", ARTIFACTS_DIR, "Artifacts confined to ~/.bitbuddy")):
        try:
            path.resolve().relative_to(APP_DIR.resolve())
            ok = True
        except ValueError:
            ok = False
        results.append(DoctorCheckResult(check_id, "Safety", "pass" if ok else "fail", title if ok else f"{path.name} directory outside ~/.bitbuddy", str(path)))
    return results


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def http_json_ok(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            raw = response.read(250_000)
        json.loads(raw.decode("utf-8") or "{}")
        return True, url
    except Exception as error:
        return False, f"{url}: {error}"


def http_search_results_ok(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=4.0) as response:
            raw = response.read(500_000)
        parsed = json.loads(raw.decode("utf-8") or "{}")
        rows = parsed.get("results") if isinstance(parsed, dict) else None
        if isinstance(rows, list) and rows:
            return True, f"{url} ({len(rows)} result(s))"
        return False, f"{url} returned 0 result(s); upstream search may be blocked or rate-limited."
    except Exception as error:
        return False, f"{url}: {error}"


def http_text_ok(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            response.read(16_000)
            return response.status < 500, url
    except Exception as error:
        return False, f"{url}: {error}"
