from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path


LOGGER = logging.getLogger(__name__)
MAX_FILE_BYTES = 750_000
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".svelte-kit",
    ".next",
    ".nuxt",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
    ".venv",
}
SKIP_SUFFIXES = {
    ".7z",
    ".avif",
    ".bin",
    ".bmp",
    ".db",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".lock",
    ".mp3",
    ".mp4",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".tar",
    ".wasm",
    ".webp",
    ".zip",
}


SYMBOL_PATTERNS = {
    "python": [
        ("python-class", re.compile(r"^\s*class\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ("python-function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)", re.MULTILINE)),
    ],
    "javascript": [
        ("js-class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("js-function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("js-const-function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE)),
    ],
    "typescript": [
        ("ts-class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("ts-function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("ts-const-function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE)),
    ],
    "svelte": [
        ("svelte-function", re.compile(r"^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
        ("svelte-state", re.compile(r"^\s*(?:let|const)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)),
    ],
    "rust": [
        ("rust-item", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|struct|enum|trait|impl)\s+([A-Za-z_][\w]*)", re.MULTILINE)),
    ],
    "go": [
        ("go-symbol", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)", re.MULTILINE)),
    ],
}


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    paths: tuple[Path, ...]
    database_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class IndexResult:
    project: Project
    scanned: int
    changed: int
    deleted: int
    skipped: int
    roots: tuple[str, ...]
    changed_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    skipped_paths: tuple[str, ...]
