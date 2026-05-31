from __future__ import annotations

from pathlib import Path


APP_DIR = Path.home() / ".bitbuddy"
CONFIG_PATH = APP_DIR / "config.yaml"
PERSONALITY_PATH = APP_DIR / "personality.yaml"
PERSONALITIES_DIR = APP_DIR / "personalities"
PROJECTS_DIR = APP_DIR / "projects"
SKILLS_DIR = APP_DIR / "skills"
ARTIFACTS_DIR = APP_DIR / "artifacts"
GLOBAL_DB_PATH = APP_DIR / "bitbuddy.sqlite"
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PERSONALITIES_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
