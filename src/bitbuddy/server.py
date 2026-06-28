from __future__ import annotations

from http.server import ThreadingHTTPServer

from .auth import get_api_token
from .config import load_config
from .http_api import BitBuddyRequestHandler
from .paths import APP_DIR, ensure_app_dirs
from .projects.watcher import start_project_monitor
from .autonomy.runner import schedule_startup_idle_autonomy
from .autonomy.delivery_scheduler import schedule_startup_intention_delivery, start_delivery_heartbeat
from .autonomy.web_search_server import ensure_web_search_server
from .calendar.scheduler import start_calendar_scheduler
from .tasks.scheduler import start_task_scheduler
from .lifecycle import start_lifecycle_monitor
from .utils import log_activity
from .web_build import ensure_web_build


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    ensure_app_dirs()
    get_api_token()
    config = load_config()

    ui_ready = ensure_web_build()
    ensure_web_search_server(config.autonomy.web_search)
    start_project_monitor(config.project_scan_interval_seconds)
    start_lifecycle_monitor()
    schedule_startup_idle_autonomy()
    schedule_startup_intention_delivery()
    start_delivery_heartbeat()
    start_calendar_scheduler()
    start_task_scheduler()

    log_activity(
        "server.started",
        "BitBuddy backend server started",
        {"host": host, "port": port},
    )

    server = ThreadingHTTPServer((host, port), BitBuddyRequestHandler)

    if ui_ready:
        print(f"BitBuddy running at http://{host}:{port} (API + web UI)")
    else:
        print(f"BitBuddy API running at http://{host}:{port} (web UI unavailable)")
    print(f"Home: {APP_DIR}")
    print(f"Project monitor refresh interval: {config.project_scan_interval_seconds}s")

    server.serve_forever()
