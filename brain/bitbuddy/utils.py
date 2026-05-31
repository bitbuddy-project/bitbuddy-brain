from __future__ import annotations

import sys
from typing import Any

from .activity import list_activity, log_activity as _log_activity


def log_activity(kind: str, message: str, metadata: dict[str, Any] | None = None) -> None:
    """Best-effort activity logging.

    Chat streaming should not fail just because the SQLite activity DB is
    temporarily unavailable. This wrapper keeps call sites simple while making
    logging non-fatal.
    """
    try:
        _log_activity(kind, message, metadata)
    except Exception as error:
        print(f"BitBuddy activity log failed: {error}", file=sys.stderr)


def autonomy_activity() -> list[dict[str, Any]]:
    return [item for item in list_activity() if not item["kind"].startswith("chat.")]


def permission_activity() -> list[dict[str, Any]]:
    return [item for item in list_activity() if "permission" in item["kind"]]


def project_to_json(project: Any) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "paths": [str(path) for path in project.paths],
        "database_path": str(project.database_path),
        "metadata_path": str(project.metadata_path),
        "access": "read-only",
    }
