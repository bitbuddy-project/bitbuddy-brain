"""Small credential storage seam.

This intentionally keeps secrets out of config.yaml and HTTP responses. It is not
encrypted-at-rest, but the file is created user-readable only and the API stores
stable references in config instead of raw API keys.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..paths import APP_DIR, ensure_app_dirs


SECRETS_PATH = APP_DIR / "secrets.json"


class SecretsBackendUnavailable(RuntimeError):
    pass


def get_credentials(ref: str | None) -> dict[str, str]:
    if not ref:
        return {}
    data = read_secrets()
    blob = data.get(ref)
    if not isinstance(blob, dict):
        return {}
    return {str(key): str(value) for key, value in blob.items() if isinstance(value, (str, int, float, bool))}


def put_credentials(ref: str, blob: dict[str, str]) -> None:
    clean_ref = str(ref or "").strip()
    if not clean_ref:
        raise ValueError("Credential reference is required.")
    data = read_secrets()
    data[clean_ref] = {str(key): str(value) for key, value in blob.items()}
    write_secrets(data)


def delete_credentials(ref: str | None) -> None:
    if not ref:
        return
    data = read_secrets()
    if data.pop(ref, None) is not None:
        write_secrets(data)


def read_secrets() -> dict[str, dict[str, Any]]:
    if not SECRETS_PATH.exists():
        return {}
    try:
        parsed = json.loads(SECRETS_PATH.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as error:
        raise SecretsBackendUnavailable(f"Could not read credential store: {error}") from error
    return parsed if isinstance(parsed, dict) else {}


def write_secrets(data: dict[str, dict[str, Any]]) -> None:
    ensure_app_dirs()
    tmp_path = SECRETS_PATH.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(SECRETS_PATH)
        os.chmod(SECRETS_PATH, 0o600)
    except OSError as error:
        raise SecretsBackendUnavailable(f"Could not write credential store: {error}") from error
