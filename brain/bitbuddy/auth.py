from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from .paths import APP_DIR, ensure_app_dirs


API_TOKEN_PATH = APP_DIR / "api_token"
API_TOKEN_HEADER = "X-BitBuddy-Token"


def api_token_path() -> Path:
    return API_TOKEN_PATH


def get_api_token() -> str:
    ensure_app_dirs()
    if API_TOKEN_PATH.exists():
        token = API_TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            try:
                os.chmod(API_TOKEN_PATH, 0o600)
            except OSError:
                pass
            return token
    token = secrets.token_urlsafe(48)
    tmp_path = API_TOKEN_PATH.with_suffix(".tmp")
    tmp_path.write_text(token + "\n", encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(API_TOKEN_PATH)
    os.chmod(API_TOKEN_PATH, 0o600)
    return token


def valid_api_token(value: str) -> bool:
    token = get_api_token()
    return bool(value) and secrets.compare_digest(value, token)


def is_allowed_origin(origin: str) -> bool:
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme == "http" and is_loopback_host(parsed.hostname or "")


def is_loopback_host(host: str) -> bool:
    clean = str(host or "").strip().strip("[]").lower()
    return clean in {"", "localhost", "127.0.0.1", "::1"} or clean.startswith("127.")
