from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .paths import APP_DIR, ensure_app_dirs


COMPUTER_USE_LINUX_VERSION = "v0.2.4"
COMPUTER_USE_LINUX_BASE_URL = f"https://github.com/agent-sh/computer-use-linux/releases/download/{COMPUTER_USE_LINUX_VERSION}"


@dataclass(frozen=True)
class ManagedToolStatus:
    name: str
    available: bool
    path: str
    source: str
    message: str


def managed_bin_dir() -> Path:
    return APP_DIR / "tools" / "bin"


def computer_use_linux_path() -> Path:
    return managed_bin_dir() / "computer-use-linux"


def computer_use_linux_cosmic_path() -> Path:
    return managed_bin_dir() / "computer-use-linux-cosmic"


def resolve_managed_command(command: str) -> str:
    if command != "managed:computer-use-linux":
        return command

    bundled = computer_use_linux_path()
    if bundled.exists():
        return str(bundled)

    system = shutil.which("computer-use-linux")
    if system:
        return system

    return str(bundled)


def computer_use_linux_status() -> ManagedToolStatus:
    bundled = computer_use_linux_path()
    if bundled.exists():
        return ManagedToolStatus("computer-use-linux", True, str(bundled), "managed", "Managed computer-use-linux is installed.")
    system = shutil.which("computer-use-linux")
    if system:
        return ManagedToolStatus("computer-use-linux", True, system, "system", "System computer-use-linux is available.")
    return ManagedToolStatus(
        "computer-use-linux",
        False,
        str(bundled),
        "missing",
        "computer-use-linux is not installed. Run `bitbuddy mcp install-computer-use-linux`.",
    )


def install_computer_use_linux() -> ManagedToolStatus:
    ensure_app_dirs()
    target = rust_linux_target()
    bin_dir = managed_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    install_release_binary("computer-use-linux", target, computer_use_linux_path())
    install_release_binary("computer-use-linux-cosmic", target, computer_use_linux_cosmic_path())
    return computer_use_linux_status()


def rust_linux_target() -> str:
    if platform.system().lower() != "linux":
        raise ValueError("computer-use-linux managed install is only supported on Linux.")
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64-unknown-linux-gnu"
    if machine in {"aarch64", "arm64"}:
        return "aarch64-unknown-linux-gnu"
    raise ValueError(f"Unsupported Linux architecture for computer-use-linux: {platform.machine()}")


def install_release_binary(binary: str, target: str, destination: Path) -> None:
    asset = f"{binary}-{target}"
    data = download_bytes(f"{COMPUTER_USE_LINUX_BASE_URL}/{asset}")
    expected_sha = download_bytes(f"{COMPUTER_USE_LINUX_BASE_URL}/{asset}.sha256").decode("utf-8").split()[0].strip()
    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(f"Checksum mismatch for {asset}: expected {expected_sha}, got {actual_sha}")
    destination.write_bytes(data)
    destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def download_bytes(url: str) -> bytes:
    override = os.environ.get("BITBUDDY_COMPUTER_USE_LINUX_DOWNLOAD_BASE")
    if override:
        url = url.replace(COMPUTER_USE_LINUX_BASE_URL, override.rstrip("/"))
    request = urllib.request.Request(url, headers={"User-Agent": "bitbuddy"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()
