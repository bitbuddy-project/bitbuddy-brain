"""Best-effort enabling of Linux desktop-control prerequisites.

BitBuddy delegates actual desktop control to the bundled ``computer-use-linux``
binary, but that binary is only useful once the session exposes accessibility,
input injection, screenshots, and window listing. This module attempts to enable
those prerequisites and reports the *true* post-state of each capability so the
assistant never claims control it does not actually have.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import update_mcp_config, upsert_mcp_server
from .managed_tools import computer_use_linux_cosmic_path, resolve_managed_command
from .paths import APP_DIR

# Accessibility env passed to the binary subprocess (mcp_client merges config.env).
ACCESSIBILITY_ENV: dict[str, str] = {
    "GTK_MODULES": "gail:atk-bridge",
    "QT_ACCESSIBILITY": "1",
    "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1",
    "NO_AT_BRIDGE": "0",
    "ACCESSIBILITY_ENABLED": "1",
}

# Status values. ``enabled`` = verified working; ``needs_user`` = a manual step is
# required; ``blocked`` = unavailable in this session and BitBuddy cannot fix it.
STATUS_ENABLED = "enabled"
STATUS_NEEDS_USER = "needs_user"
STATUS_BLOCKED = "blocked"


@dataclass
class CapabilityResult:
    name: str
    status: str
    detail: str
    remediation: str = ""


@dataclass
class DesktopControlReport:
    capabilities: list[CapabilityResult] = field(default_factory=list)
    doctor_ok: bool = False
    doctor_output: str = ""

    @property
    def ready(self) -> bool:
        return self.doctor_ok and all(cap.status == STATUS_ENABLED for cap in self.capabilities)


def _run(cmd: list[str], timeout: float = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _process_running(name: str) -> bool:
    if shutil.which("pgrep") is None:
        return False
    return _run(["pgrep", "-x", name]).returncode == 0


def ydotool_socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else (APP_DIR / "run")
    return base / ".ydotool_socket"


def _enable_accessibility() -> CapabilityResult:
    if shutil.which("gsettings") is None:
        # Toolkit-less stacks: env is the only lever, which we persist regardless.
        return CapabilityResult(
            "accessibility",
            STATUS_NEEDS_USER,
            "gsettings not found; persisted AT-SPI env vars for the desktop-control binary.",
            "Ensure your toolkit exposes AT-SPI (e.g. install at-spi2-core) and restart the target apps.",
        )
    try:
        _run(["gsettings", "set", "org.gnome.desktop.interface", "toolkit-accessibility", "true"])
        readback = _run(["gsettings", "get", "org.gnome.desktop.interface", "toolkit-accessibility"])
    except Exception as error:  # pragma: no cover - environment dependent
        return CapabilityResult("accessibility", STATUS_NEEDS_USER, f"gsettings failed: {error}", "Enable toolkit-accessibility manually.")
    if "true" in readback.stdout.strip().lower():
        return CapabilityResult("accessibility", STATUS_ENABLED, "AT-SPI toolkit-accessibility is enabled.")
    return CapabilityResult(
        "accessibility",
        STATUS_NEEDS_USER,
        "Could not confirm toolkit-accessibility is on.",
        "Run `gsettings set org.gnome.desktop.interface toolkit-accessibility true` and restart target apps.",
    )


def _detect_ydotool_socket() -> Path | None:
    candidates = [ydotool_socket_path()]
    env_sock = os.environ.get("YDOTOOL_SOCKET")
    if env_sock:
        candidates.append(Path(env_sock))
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        candidates.append(Path(runtime) / ".ydotool_socket")
    candidates.append(Path(f"/run/user/{os.getuid()}/.ydotool_socket"))
    candidates.append(Path("/tmp/.ydotool_socket"))
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def _enable_ydotool(env_updates: dict[str, str]) -> CapabilityResult:
    if shutil.which("ydotoold") is None:
        return CapabilityResult(
            "ydotool",
            STATUS_NEEDS_USER,
            "ydotoold is not installed.",
            "Install the `ydotool` package (provides ydotoold) and re-run setup.",
        )
    if _process_running("ydotoold"):
        sock = _detect_ydotool_socket()
        if sock is not None:
            env_updates["YDOTOOL_SOCKET"] = str(sock)
        return CapabilityResult("ydotool", STATUS_ENABLED, f"ydotoold already running ({sock or 'default socket'}).")
    if not os.access("/dev/uinput", os.W_OK):
        return CapabilityResult(
            "ydotool",
            STATUS_NEEDS_USER,
            "/dev/uinput is not writable, so ydotoold cannot inject input.",
            "Add a udev rule granting the `input` group access to /dev/uinput (or run ydotoold privileged), then re-run setup.",
        )

    sock = ydotool_socket_path()
    sock.parent.mkdir(parents=True, exist_ok=True)
    proc_env = os.environ.copy()
    proc_env["YDOTOOL_SOCKET"] = str(sock)
    # Prefer the user service when packaged; fall back to launching the daemon directly.
    started = False
    if shutil.which("systemctl") is not None:
        unit = _run(["systemctl", "--user", "start", "ydotoold"])
        started = unit.returncode == 0
    if not started:
        try:
            subprocess.Popen(  # noqa: S603 - launching a known daemon
                ["ydotoold"],
                env=proc_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as error:  # pragma: no cover - environment dependent
            return CapabilityResult("ydotool", STATUS_NEEDS_USER, f"Failed to start ydotoold: {error}", "Start ydotoold manually.")

    for _ in range(10):
        if _process_running("ydotoold"):
            break
        time.sleep(0.2)
    detected = _detect_ydotool_socket()
    if _process_running("ydotoold") and detected is not None:
        env_updates["YDOTOOL_SOCKET"] = str(detected)
        return CapabilityResult("ydotool", STATUS_ENABLED, f"Started ydotoold ({detected}).")
    return CapabilityResult(
        "ydotool",
        STATUS_NEEDS_USER,
        "Started ydotoold but could not confirm its socket.",
        "Verify ydotoold is running and check its socket path, then re-run setup.",
    )


def _select_binary_for_compositor() -> tuple[str, CapabilityResult]:
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    is_cosmic = "cosmic" in desktop
    if is_cosmic and computer_use_linux_cosmic_path().exists():
        return str(computer_use_linux_cosmic_path()), CapabilityResult(
            "window_listing",
            STATUS_ENABLED,
            "COSMIC detected; using the computer-use-linux-cosmic binary for window listing.",
        )
    if is_cosmic:
        return "managed:computer-use-linux", CapabilityResult(
            "window_listing",
            STATUS_NEEDS_USER,
            "COSMIC detected but the cosmic binary is missing.",
            "Run `bitbuddy mcp install-computer-use-linux` to install the cosmic variant.",
        )
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if wayland:
        return "managed:computer-use-linux", CapabilityResult(
            "window_listing",
            STATUS_NEEDS_USER,
            f"Wayland compositor '{desktop or 'unknown'}' may not expose window listing/focus.",
            "Window listing needs wlr-foreign-toplevel-management (most wlroots compositors) or an X11 session.",
        )
    return "managed:computer-use-linux", CapabilityResult(
        "window_listing",
        STATUS_ENABLED,
        f"X11 session ('{desktop or 'unknown'}') supports window listing.",
    )


def _check_portal() -> CapabilityResult:
    if _process_running("xdg-desktop-portal"):
        return CapabilityResult("screenshot_portal", STATUS_ENABLED, "xdg-desktop-portal is running.")
    return CapabilityResult(
        "screenshot_portal",
        STATUS_BLOCKED,
        "xdg-desktop-portal is not running; screenshot capture is unavailable.",
        "Install/start xdg-desktop-portal plus the backend for your compositor (e.g. xdg-desktop-portal-wlr or -gnome), then re-login.",
    )


def _run_doctor() -> tuple[bool, str]:
    command = resolve_managed_command("managed:computer-use-linux")
    try:
        result = _run([command, "doctor"], timeout=60)
    except Exception as error:  # pragma: no cover - environment dependent
        return False, f"Failed to run desktop-control doctor: {error}"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()[:8000]


def enable_desktop_control() -> DesktopControlReport:
    """Attempt to enable each desktop-control prerequisite and report the result."""
    if not sys.platform.startswith("linux"):
        return DesktopControlReport(
            capabilities=[CapabilityResult("platform", STATUS_BLOCKED, "Desktop control is only supported on Linux.")],
        )

    env_updates: dict[str, str] = dict(ACCESSIBILITY_ENV)
    capabilities = [_enable_accessibility(), _enable_ydotool(env_updates)]
    command, window_cap = _select_binary_for_compositor()
    capabilities.append(window_cap)
    capabilities.append(_check_portal())

    update_mcp_config({"enabled": True})
    upsert_mcp_server(
        "computer-use-linux",
        command,
        ["mcp"],
        timeout=120,
        connect_timeout=30,
        enabled=True,
        env=env_updates,
    )

    doctor_ok, doctor_output = _run_doctor()
    return DesktopControlReport(capabilities=capabilities, doctor_ok=doctor_ok, doctor_output=doctor_output)


def report_to_json(report: DesktopControlReport) -> dict[str, object]:
    return {
        "ready": report.ready,
        "doctor_ok": report.doctor_ok,
        "doctor_output": report.doctor_output,
        "capabilities": [
            {"name": cap.name, "status": cap.status, "detail": cap.detail, "remediation": cap.remediation}
            for cap in report.capabilities
        ],
    }


def render_report(report: DesktopControlReport) -> str:
    symbols = {STATUS_ENABLED: "✓", STATUS_NEEDS_USER: "!", STATUS_BLOCKED: "✗"}
    lines = ["Desktop-control setup:"]
    for cap in report.capabilities:
        lines.append(f"  [{symbols.get(cap.status, '?')}] {cap.name}: {cap.detail}")
        if cap.remediation and cap.status != STATUS_ENABLED:
            lines.append(f"      → {cap.remediation}")
    lines.append("")
    lines.append(f"doctor: {'ok' if report.doctor_ok else 'reported issues'}")
    if report.doctor_output:
        lines.append(report.doctor_output)
    return "\n".join(lines)
