from __future__ import annotations

import ctypes
import os
import select
import struct
import threading
import time
from pathlib import Path
from typing import Any

from ..librarian import regenerate_card
from ..memory.project import (
    SKIP_DIRS,
    index_project,
    list_projects,
    project_has_completed_scan,
)
from ..utils import log_activity


def start_project_monitor(interval_seconds: int) -> None:
    if interval_seconds <= 0:
        log_activity("monitor.disabled", "Project memory monitor is disabled")
        return

    def monitor() -> None:
        try:
            watcher = ProjectChangeWatcher()
        except OSError as error:
            log_activity(
                "monitor.failed",
                "Project memory monitor could not start filesystem watcher",
                {"error": str(error)},
            )
            return

        last_project_refresh = 0.0
        dirty_projects: dict[str, float] = {}
        project_names: dict[str, str] = {}

        try:
            while True:
                now = time.monotonic()

                if now - last_project_refresh >= interval_seconds:
                    try:
                        refresh_project_watches(watcher, project_names)
                    except Exception as error:
                        log_activity(
                            "monitor.refresh_failed",
                            "Project memory monitor refresh failed",
                            {"error": str(error)},
                        )

                    last_project_refresh = now

                for project_id in watcher.read_changed_project_ids():
                    dirty_projects[project_id] = time.monotonic()

                ready = [
                    project_id
                    for project_id, changed_at in dirty_projects.items()
                    if time.monotonic() - changed_at >= 0.8
                ]

                for project_id in ready:
                    dirty_projects.pop(project_id, None)
                    project_name = project_names.get(project_id, project_id)
                    index_project_from_monitor(project_id, project_name, initial=False)

                time.sleep(0.1)
        finally:
            watcher.close()

    thread = threading.Thread(target=monitor, name="bitbuddy-project-monitor", daemon=True)
    thread.start()

    log_activity(
        "monitor.started",
        "Project memory monitor started",
        {"mode": "filesystem-events", "project_refresh_seconds": interval_seconds},
    )


def refresh_project_watches(watcher: "ProjectChangeWatcher", project_names: dict[str, str]) -> None:
    for project in list_projects():
        project_names[project.id] = project.name

        try:
            watcher.watch_project(project)
        except OSError as error:
            log_activity(
                "monitor.watch_failed",
                f"Project memory monitor could not watch {project.name}",
                {"project_id": project.id, "error": str(error)},
            )
            continue

        if not project_has_completed_scan(project.id):
            index_project_from_monitor(project.id, project.name, initial=True)


def index_project_from_monitor(project_id: str, project_name: str, initial: bool) -> None:
    try:
        result = index_project(project_id, record_activity=False)

        if initial:
            log_activity(
                "project.initial_indexed",
                f"Initially indexed project memory {project_name}",
                project_result_metadata(result),
            )
        elif result.changed or result.deleted:
            log_activity(
                "project.changed",
                f"Detected project memory changes in {project_name}",
                project_result_metadata(result),
            )

        try:
            regenerate_card(project_id)
        except Exception as card_error:
            log_activity(
                "librarian.card_failed",
                f"Failed to regenerate librarian card for {project_name}",
                {"project_id": project_id, "error": str(card_error)},
            )
    except Exception as error:
        log_activity(
            "project.scan_failed",
            f"Project memory scan failed for {project_name}",
            {"project_id": project_id, "error": str(error)},
        )


def project_result_metadata(result: Any) -> dict[str, Any]:
    return {
        "project_id": result.project.id,
        "roots": result.roots,
        "scanned": result.scanned,
        "changed": result.changed,
        "deleted": result.deleted,
        "skipped": result.skipped,
        "changed_paths": result.changed_paths[:25],
        "deleted_paths": result.deleted_paths[:25],
        "skipped_paths": result.skipped_paths[:25],
    }


class ProjectChangeWatcher:
    IN_MODIFY = 0x00000002
    IN_ATTRIB = 0x00000004
    IN_CLOSE_WRITE = 0x00000008
    IN_MOVED_FROM = 0x00000040
    IN_MOVED_TO = 0x00000080
    IN_CREATE = 0x00000100
    IN_DELETE = 0x00000200
    IN_DELETE_SELF = 0x00000400
    IN_MOVE_SELF = 0x00000800
    IN_ISDIR = 0x40000000

    EVENT_STRUCT = struct.Struct("iIII")

    WATCH_MASK = (
        IN_MODIFY
        | IN_ATTRIB
        | IN_CLOSE_WRITE
        | IN_MOVED_FROM
        | IN_MOVED_TO
        | IN_CREATE
        | IN_DELETE
        | IN_DELETE_SELF
        | IN_MOVE_SELF
    )

    def __init__(self) -> None:
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self.fd = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)

        if self.fd < 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))

        self._watched_project_ids: set[str] = set()
        self._wd_to_project_id: dict[int, str] = {}
        self._wd_to_path: dict[int, Path] = {}
        self._watched_paths: set[Path] = set()

    def watch_project(self, project: Any) -> None:
        if project.id in self._watched_project_ids:
            return

        for root in project.paths:
            watch_root = root if root.is_dir() else root.parent
            self._watch_directory_tree(project.id, watch_root)

        self._watched_project_ids.add(project.id)

    def read_changed_project_ids(self) -> set[str]:
        ready, _, _ = select.select([self.fd], [], [], 0)

        if not ready:
            return set()

        changed: set[str] = set()

        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break

            if not data:
                break

            offset = 0

            while offset + self.EVENT_STRUCT.size <= len(data):
                wd, mask, _cookie, name_length = self.EVENT_STRUCT.unpack_from(data, offset)
                offset += self.EVENT_STRUCT.size

                raw_name = data[offset : offset + name_length].split(b"\0", 1)[0]
                offset += name_length

                project_id = self._wd_to_project_id.get(wd)

                if not project_id:
                    continue

                changed.add(project_id)

                if mask & self.IN_ISDIR and mask & (self.IN_CREATE | self.IN_MOVED_TO):
                    parent = self._wd_to_path.get(wd)

                    if parent and raw_name:
                        new_dir = parent / raw_name.decode("utf-8", errors="replace")

                        if new_dir.exists():
                            self._watch_directory_tree(project_id, new_dir)

        return changed

    def close(self) -> None:
        os.close(self.fd)

    def _watch_directory_tree(self, project_id: str, root: Path) -> None:
        if not root.exists():
            return

        for current_root, dirnames, _filenames in os.walk(root):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in SKIP_DIRS]
            self._watch_directory(project_id, Path(current_root))

    def _watch_directory(self, project_id: str, path: Path) -> None:
        resolved = path.resolve()

        if resolved in self._watched_paths:
            return

        wd = self._libc.inotify_add_watch(self.fd, os.fsencode(resolved), self.WATCH_MASK)

        if wd < 0:
            return

        self._watched_paths.add(resolved)
        self._wd_to_project_id[wd] = project_id
        self._wd_to_path[wd] = resolved
