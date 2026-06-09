from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from ..activity import ensure_activity_database
from ..autonomy.intentions import ensure_intentions_database
from ..calendar.store import ensure_calendar_database
from ..chats.repository import ensure_chat_database
from ..config import CONFIG_PATH, write_config
from ..continuity import ensure_continuity_database
from ..dreaming.runtime import ensure_dream_database
from ..lifecycle import ensure_lifecycle_database
from ..loop_learning import ensure_loop_learning_database
from ..memory.episodic import ensure_episodic_memory_database
from ..memory.project_registry import ensure_global_database
from ..memory.store import ensure_memory_database
from ..notifications import ensure_notification_database
from ..paths import APP_DIR, WEB_DIR, ensure_app_dirs
from ..personality import seed_builtin_personality_files
from ..self_model import ensure_self_model_database
from ..self_notes import ensure_self_notes_database
from ..subagents.runtime import ensure_subagent_database
from ..workspace import ensure_workspace_database
from .checks import run_doctor_checks
from .report import DoctorCheckResult, doctor_exit_code, render_doctor_report


@dataclass(frozen=True)
class DoctorFixResult:
    fix_id: str
    ok: bool
    message: str


Fixer = Callable[[], DoctorFixResult]


def run_doctor_fix() -> tuple[list[DoctorFixResult], list[DoctorCheckResult], int]:
    before = run_doctor_checks()
    fix_ids = sorted({result.fix_id for result in before if result.fix_id and result.status in {"fail", "warn"}})
    fixes: list[DoctorFixResult] = []
    for fix_id in fix_ids:
        fixer = FIXERS.get(fix_id)
        if fixer is None:
            fixes.append(DoctorFixResult(fix_id, False, "No automatic fixer is registered for this issue."))
            continue
        try:
            fixes.append(fixer())
        except Exception as error:
            fixes.append(DoctorFixResult(fix_id, False, str(error)))
    after = run_doctor_checks()
    return fixes, after, doctor_exit_code(after)


def render_fix_report(fixes: list[DoctorFixResult], after: list[DoctorCheckResult]) -> str:
    lines = ["BitBuddy Doctor Fix", ""]
    if not fixes:
        lines.extend(["No safe automatic fixes were needed.", ""])
    else:
        lines.append("Applied fixes")
        for fix in fixes:
            symbol = "✓" if fix.ok else "✗"
            lines.append(f"  {symbol} {fix.fix_id}: {fix.message}")
        lines.append("")
    lines.append(render_doctor_report(after).rstrip())
    return "\n".join(lines) + "\n"


def backup_config() -> Path | None:
    if not CONFIG_PATH.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.bak-{timestamp}")
    shutil.copy2(CONFIG_PATH, backup)
    return backup


def fix_dirs() -> DoctorFixResult:
    ensure_app_dirs()
    (APP_DIR / "tools" / "bin").mkdir(parents=True, exist_ok=True)
    return DoctorFixResult("dirs.ensure", True, "Created missing BitBuddy-owned directories.")


def fix_config_create_default() -> DoctorFixResult:
    ensure_app_dirs()
    if CONFIG_PATH.exists():
        return DoctorFixResult("config.create_default", True, "Config already exists; left it unchanged.")
    write_config("none", "", "")
    return DoctorFixResult("config.create_default", True, f"Created default config at {CONFIG_PATH}.")


def fix_config_reset_default() -> DoctorFixResult:
    ensure_app_dirs()
    backup = backup_config()
    write_config("none", "", "")
    detail = f" Backed up previous config to {backup}." if backup else ""
    return DoctorFixResult("config.reset_default", True, f"Wrote a safe default config.{detail}")


def fix_db_init() -> DoctorFixResult:
    ensure_app_dirs()
    ensure_activity_database()
    ensure_chat_database()
    ensure_memory_database()
    ensure_episodic_memory_database()
    ensure_global_database()
    ensure_intentions_database()
    ensure_lifecycle_database()
    ensure_dream_database()
    ensure_workspace_database()
    ensure_notification_database()
    ensure_self_model_database()
    ensure_self_notes_database()
    ensure_continuity_database()
    ensure_calendar_database()
    ensure_subagent_database()
    ensure_loop_learning_database()
    seed_builtin_personality_files()
    return DoctorFixResult("db.init", True, "Initialized missing SQLite tables and built-in personality files.")


def fix_web_npm_install() -> DoctorFixResult:
    if not (WEB_DIR / "package.json").is_file():
        return DoctorFixResult("web.npm_install", False, f"Cannot install web dependencies; package.json is missing at {WEB_DIR}.")
    npm = shutil.which("npm")
    if not npm:
        return DoctorFixResult("web.npm_install", False, "npm is not available on PATH.")
    completed = subprocess.run([npm, "install"], cwd=WEB_DIR, text=True, capture_output=True, timeout=300)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "npm install failed").strip().splitlines()[-1]
        return DoctorFixResult("web.npm_install", False, detail)
    return DoctorFixResult("web.npm_install", True, "Installed local web dependencies with npm install.")


def fix_web_search_defaults() -> DoctorFixResult:
    ensure_app_dirs()
    backup = backup_config()
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    if not isinstance(raw, dict):
        raw = {}
    autonomy = raw.get("autonomy") if isinstance(raw.get("autonomy"), dict) else {}
    autonomy["web_search"] = {
        "enabled": True,
        "provider": "searxng",
        "url": "http://127.0.0.1:8888",
        "startup_command": "managed",
        "max_results": 5,
    }
    raw["autonomy"] = autonomy
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    detail = f" Backed up previous config to {backup}." if backup else ""
    return DoctorFixResult("web_search.reset_defaults", True, f"Reset web search to managed local defaults.{detail}")


def fix_config_clamp_safe() -> DoctorFixResult:
    ensure_app_dirs()
    backup = backup_config()
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    if not isinstance(raw, dict):
        raw = {}
    autonomy = raw.get("autonomy") if isinstance(raw.get("autonomy"), dict) else {}
    if "idle_delay_seconds" in autonomy:
        autonomy["idle_delay_seconds"] = max(0, float(autonomy.get("idle_delay_seconds") or 0))
    if "idle_backoff_multiplier" in autonomy:
        autonomy["idle_backoff_multiplier"] = max(1.0, float(autonomy.get("idle_backoff_multiplier") or 1.0))
    if "idle_max_delay_seconds" in autonomy:
        autonomy["idle_max_delay_seconds"] = max(float(autonomy.get("idle_delay_seconds") or 0), float(autonomy.get("idle_max_delay_seconds") or 0))
    if "max_autonomous_deliveries_per_day" in autonomy:
        autonomy["max_autonomous_deliveries_per_day"] = max(1, int(autonomy.get("max_autonomous_deliveries_per_day") or 1))
    raw["autonomy"] = autonomy
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    detail = f" Backed up previous config to {backup}." if backup else ""
    return DoctorFixResult("config.clamp_safe", True, f"Clamped unsafe numeric config values.{detail}")


FIXERS: dict[str, Fixer] = {
    "dirs.ensure": fix_dirs,
    "config.create_default": fix_config_create_default,
    "config.reset_default": fix_config_reset_default,
    "db.init": fix_db_init,
    "web.npm_install": fix_web_npm_install,
    "web_search.reset_defaults": fix_web_search_defaults,
    "config.clamp_safe": fix_config_clamp_safe,
}
