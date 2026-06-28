"""Build the web UI on demand so `bitbuddy serve` can host it.

The backend serves the static SPA from ``web/build`` (see http_api). When
running from source that directory may be missing or stale, so we rebuild it
lazily. A packaged install ships a prebuilt ``web/build`` whose stamp is newer
than its sources, so the staleness check passes and nothing runs here — no
Node/pnpm required at runtime.
"""

from __future__ import annotations

import shutil
import subprocess

from .paths import WEB_BUILD_DIR, WEB_DIR
from .utils import log_activity


# Source files that, when changed, should invalidate the build.
_SOURCE_DIRS = ("src", "static")
_SOURCE_FILES = ("package.json", "svelte.config.js", "vite.config.ts", "pnpm-lock.yaml")


def _detect_package_manager() -> str | None:
    """Prefer pnpm (the repo's lockfile) but fall back to npm."""
    if (WEB_DIR / "pnpm-lock.yaml").is_file() and shutil.which("pnpm"):
        return "pnpm"
    if shutil.which("pnpm"):
        return "pnpm"
    if shutil.which("npm"):
        return "npm"
    return None


def _newest_source_mtime() -> float:
    newest = 0.0
    for name in _SOURCE_DIRS:
        directory = WEB_DIR / name
        if not directory.is_dir():
            continue
        for entry in directory.rglob("*"):
            if entry.is_file():
                newest = max(newest, entry.stat().st_mtime)
    for name in _SOURCE_FILES:
        candidate = WEB_DIR / name
        if candidate.is_file():
            newest = max(newest, candidate.stat().st_mtime)
    return newest


def _build_is_stale() -> bool:
    index_html = WEB_BUILD_DIR / "index.html"
    if not index_html.is_file():
        return True
    return _newest_source_mtime() > index_html.stat().st_mtime


def ensure_web_build(*, force: bool = False) -> bool:
    """Ensure ``web/build`` exists and is current. Returns True if usable.

    Never raises: if the sources or a package manager are unavailable, or the
    build fails, it logs a warning and returns False so the caller can keep
    serving the API.
    """
    if not WEB_DIR.is_dir():
        return (WEB_BUILD_DIR / "index.html").is_file()

    if not force and not _build_is_stale():
        return True

    manager = _detect_package_manager()
    if manager is None:
        log_activity(
            "web.build.skipped",
            "Skipped web UI build: no pnpm or npm found on PATH.",
            {"web_dir": str(WEB_DIR)},
        )
        print("Could not build the web UI (pnpm/npm not found). Serving API only; run `pnpm --dir web run build`.")
        return (WEB_BUILD_DIR / "index.html").is_file()

    if not (WEB_DIR / "node_modules").is_dir():
        print(f"Installing web UI dependencies with {manager} ...")
        install = subprocess.run([manager, "install"], cwd=WEB_DIR)
        if install.returncode != 0:
            log_activity(
                "web.build.failed",
                "Web UI dependency install failed.",
                {"manager": manager, "returncode": install.returncode},
            )
            print("Could not install web UI dependencies. Serving API only.")
            return (WEB_BUILD_DIR / "index.html").is_file()

    print(f"Building web UI with {manager} ...")
    result = subprocess.run([manager, "run", "build"], cwd=WEB_DIR)
    if result.returncode != 0:
        log_activity(
            "web.build.failed",
            "Web UI build failed.",
            {"manager": manager, "returncode": result.returncode},
        )
        print(f"Could not build the web UI. Serving API only; run `{manager} --dir web run build` to retry.")
        return (WEB_BUILD_DIR / "index.html").is_file()

    log_activity("web.build.completed", "Web UI build completed.", {"manager": manager})
    return (WEB_BUILD_DIR / "index.html").is_file()
