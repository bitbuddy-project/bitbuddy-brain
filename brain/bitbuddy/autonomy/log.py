from __future__ import annotations

from typing import Any

from ..utils import log_activity


def log_autonomy(kind: str, message: str, metadata: dict[str, Any] | None = None) -> None:
    log_activity(f"autonomy.{kind}", message, metadata or {})
