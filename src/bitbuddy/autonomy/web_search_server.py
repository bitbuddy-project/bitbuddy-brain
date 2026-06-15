from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TYPE_CHECKING

from ..utils import log_activity
from .web_search import BROWSER_USER_AGENT, SearchResult, normalize_search_category, safe_result_url

if TYPE_CHECKING:
    from ..config import WebSearchConfig


MANAGED_STARTUP_COMMANDS = {"", "managed", "builtin", "bitbuddy", "searxng"}
_managed_server: ThreadingHTTPServer | None = None
_managed_thread: threading.Thread | None = None


class SearchProviderBlocked(ValueError):
    pass


def ensure_web_search_server(config: WebSearchConfig) -> None:
    if not config.enabled:
        return

    if is_server_running(config.url):
        return

    if should_use_managed_server(config.startup_command):
        ensure_managed_web_search_server(config)
        return

    log_activity(
        "web_search.server_starting",
        f"Web search server not found at {config.url}. Attempting to start with: {config.startup_command}",
    )

    try:
        # Run the command in a new session so it persists after BitBuddy exits if needed,
        # or at least doesn't get immediately killed by some signals.
        subprocess.Popen(
            config.startup_command,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Poll for a few seconds
        for _ in range(5):
            time.sleep(1)
            if is_server_running(config.url):
                log_activity("web_search.server_started", f"Web search server started at {config.url}")
                return

        log_activity(
            "web_search.server_start_failed",
            f"Web search server failed to respond at {config.url} after starting.",
        )
    except Exception as error:
        log_activity(
            "web_search.server_error",
            f"Failed to start web search server: {error}",
        )


def should_use_managed_server(startup_command: str) -> bool:
    return startup_command.strip().lower() in MANAGED_STARTUP_COMMANDS


def ensure_managed_web_search_server(config: WebSearchConfig) -> None:
    global _managed_server, _managed_thread

    if _managed_server is not None:
        return

    host, port = parse_bind_address(config.url)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        log_activity(
            "web_search.server_error",
            f"Managed web search only binds local addresses, not {host!r}.",
        )
        return

    log_activity(
        "web_search.server_starting",
        f"Starting BitBuddy-managed SearxNG-compatible web search at {config.url}.",
    )

    try:
        _managed_server = ThreadingHTTPServer((host, port), ManagedWebSearchHandler)
        _managed_thread = threading.Thread(
            target=_managed_server.serve_forever,
            name="bitbuddy-web-search",
            daemon=True,
        )
        _managed_thread.start()

        for _ in range(10):
            time.sleep(0.2)
            if is_server_running(config.url):
                log_activity(
                    "web_search.server_started",
                    f"BitBuddy-managed web search started at {config.url}.",
                )
                return

        log_activity(
            "web_search.server_start_failed",
            f"BitBuddy-managed web search failed to respond at {config.url} after starting.",
        )
    except Exception as error:
        _managed_server = None
        _managed_thread = None
        log_activity(
            "web_search.server_error",
            f"Failed to start BitBuddy-managed web search: {error}",
        )


def parse_bind_address(url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def is_server_running(url: str) -> bool:
    try:
        # Check /status first (common for SearxNG)
        with urllib.request.urlopen(f"{url.rstrip('/')}/status", timeout=1) as response:
            if response.status < 400:
                return True
    except Exception:
        pass

    try:
        # Fallback to main URL
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status < 400
    except Exception:
        return False


class ManagedWebSearchHandler(BaseHTTPRequestHandler):
    server_version = "BitBuddyWebSearch/0.1"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/status":
            self.write_json({"status": "ok", "service": "bitbuddy-web-search", "api": "searxng-compatible"})
            return

        if parsed.path == "/search":
            params = urllib.parse.parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            category = params.get("categories", params.get("category", ["general"]))[0]
            self.write_json(search_response(query, category=category))
            return

        self.write_json({"status": "ok", "service": "bitbuddy-web-search"})

    def write_json(self, payload: dict[str, object], status: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, _format: str, *args: object) -> None:
        return


def search_response(query: str, limit: int = 10, category: str = "general") -> dict[str, object]:
    clean_query = " ".join(query.split())
    clean_category = normalize_search_category(category)
    if not clean_query:
        return {"query": clean_query, "results": [], "answers": [], "suggestions": []}

    try:
        if clean_category == "images":
            results = search_duckduckgo_images(clean_query, limit=limit)
        else:
            results = search_general_web(clean_query, limit=limit)
    except Exception as error:
        log_activity("web_search.search_error", f"Managed web search failed: {error}", {"query": clean_query, "category": clean_category})
        results = []

    return {
        "query": clean_query,
        "results": [
            {
                "title": result.title,
                "url": result.url,
                "content": result.snippet,
                "img_src": result.image_url,
                "thumbnail_src": result.thumbnail_url,
                "engine": result.source,
                "category": result.category,
            }
            for result in results
        ],
        "answers": [],
        "suggestions": [],
    }


def search_general_web(query: str, limit: int = 10) -> list[SearchResult]:
    providers = [
        ("duckduckgo_html", search_duckduckgo_html),
        ("duckduckgo_lite", search_duckduckgo_lite),
        ("mojeek", search_mojeek_html),
    ]
    for provider_name, search_func in providers:
        try:
            results = search_func(query, limit=limit)
        except SearchProviderBlocked as error:
            log_activity(
                "web_search.provider_blocked",
                f"Managed web search provider blocked or challenged the request: {provider_name}.",
                {"query": query, "provider": provider_name, "error": str(error)},
            )
            continue
        except Exception as error:
            log_activity(
                "web_search.provider_error",
                f"Managed web search provider failed: {provider_name}: {error}",
                {"query": query, "provider": provider_name, "error": str(error)},
            )
            continue
        if results:
            return results
        log_activity(
            "web_search.provider_empty",
            f"Managed web search provider returned no results: {provider_name}.",
            {"query": query, "provider": provider_name},
        )

    log_activity(
        "web_search.search_empty",
        "Managed web search returned no results after trying all providers.",
        {"query": query, "providers": [name for name, _func in providers]},
    )
    return []


def search_duckduckgo_html(query: str, limit: int = 10) -> list[SearchResult]:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?{params}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": BROWSER_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        html = response.read(1_500_000).decode("utf-8", errors="replace")
        raise_if_blocked("duckduckgo_html", getattr(response, "status", 200), html)
    return parse_duckduckgo_html_results(html, limit=limit)


def search_duckduckgo_lite(query: str, limit: int = 10) -> list[SearchResult]:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://lite.duckduckgo.com/lite/?{params}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": BROWSER_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        html = response.read(1_500_000).decode("utf-8", errors="replace")
        raise_if_blocked("duckduckgo_lite", getattr(response, "status", 200), html)
    parser = DuckDuckGoLiteHTMLParser()
    parser.feed(html)
    parser._flush_current()
    return parser.results[:limit]


def search_mojeek_html(query: str, limit: int = 10) -> list[SearchResult]:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://www.mojeek.com/search?{params}",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": BROWSER_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        html = response.read(1_500_000).decode("utf-8", errors="replace")
        raise_if_blocked("mojeek", getattr(response, "status", 200), html)
    parser = MojeekHTMLParser()
    parser.feed(html)
    parser._flush_current()
    return parser.results[:limit]


def raise_if_blocked(provider: str, status: int, html: str) -> None:
    lower = html[:20000].lower()
    blocked_markers = (
        "anomaly detected",
        "challenge",
        "captcha",
        "unusual traffic",
        "automated requests",
        "verify you are human",
    )
    if status == 202 or any(marker in lower for marker in blocked_markers):
        raise SearchProviderBlocked(f"{provider} returned a blocked/challenge page (HTTP {status}).")


def search_duckduckgo_images(query: str, limit: int = 10) -> list[SearchResult]:
    vqd = fetch_duckduckgo_vqd(query)
    params = urllib.parse.urlencode({"l": "us-en", "o": "json", "q": query, "vqd": vqd, "f": ",,,", "p": "1"})
    request = urllib.request.Request(
        f"https://duckduckgo.com/i.js?{params}",
        headers={
            "Accept": "application/json",
            "Referer": f"https://duckduckgo.com/?{urllib.parse.urlencode({'q': query, 'iax': 'images', 'ia': 'images'})}",
            "User-Agent": "Mozilla/5.0 (compatible; BitBuddy/0.1; local image search)",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.loads(response.read(1_500_000).decode("utf-8", errors="replace"))
    return parse_duckduckgo_image_results(data, limit=limit)


def fetch_duckduckgo_vqd(query: str) -> str:
    params = urllib.parse.urlencode({"q": query, "iax": "images", "ia": "images"})
    request = urllib.request.Request(
        f"https://duckduckgo.com/?{params}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; BitBuddy/0.1; local image search)"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        html = response.read(1_000_000).decode("utf-8", errors="replace")
    for pattern in (r"vqd=['\"]([^'\"]+)", r"['\"]vqd['\"]\s*:\s*['\"]([^'\"]+)"):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    raise ValueError("DuckDuckGo image token was not found.")


def parse_duckduckgo_image_results(data: dict[str, Any], limit: int = 10) -> list[SearchResult]:
    rows = data.get("results") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    results: list[SearchResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = normalize_text(str(row.get("title") or row.get("source") or "Image result"))
        image_url = str(row.get("image") or "").strip()
        thumbnail_url = str(row.get("thumbnail") or "").strip()
        url = str(row.get("url") or row.get("source") or image_url).strip()
        snippet_parts = [str(row.get("source") or "").strip()]
        width = row.get("width")
        height = row.get("height")
        if width and height:
            snippet_parts.append(f"{width}x{height}")
        snippet = " | ".join(part for part in snippet_parts if part)
        if not title or not safe_result_url(url) or not safe_result_url(image_url):
            continue
        if thumbnail_url and not safe_result_url(thumbnail_url):
            thumbnail_url = ""
        results.append(
            SearchResult(
                title=title[:300],
                url=url,
                snippet=snippet[:1000],
                source="duckduckgo",
                category="images",
                image_url=image_url,
                thumbnail_url=thumbnail_url,
            )
        )
        if len(results) >= limit:
            break
    return results


def parse_duckduckgo_html_results(html: str, limit: int = 10) -> list[SearchResult]:
    parser = DuckDuckGoHTMLParser()
    parser.feed(html)
    return parser.results[:limit]


@dataclass
class _PartialResult:
    title: str = ""
    url: str = ""
    snippet: str = ""


class DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._current: _PartialResult | None = None
        self._collecting_title = False
        self._collecting_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())

        if tag == "a" and "result__a" in classes:
            self._current = _PartialResult(url=normalize_duckduckgo_url(attr_map.get("href", "")))
            self._collecting_title = True
            self._title_parts = []
            return

        if self._current is not None and "result__snippet" in classes:
            self._collecting_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._collecting_title:
            self._title_parts.append(data)
        if self._collecting_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._collecting_title and self._current is not None:
            self._current.title = normalize_text(" ".join(self._title_parts))
            self._collecting_title = False
            return

        if self._collecting_snippet and tag in {"a", "div"} and self._current is not None:
            self._current.snippet = normalize_text(" ".join(self._snippet_parts))
            self._collecting_snippet = False
            self._finish_current()

    def _finish_current(self) -> None:
        if self._current is None:
            return
        if self._current.title and safe_result_url(self._current.url):
            self.results.append(
                SearchResult(
                    title=self._current.title[:300],
                    url=self._current.url,
                    snippet=self._current.snippet[:1000],
                    source="duckduckgo",
                    category="general",
                )
            )
        self._current = None
        self._title_parts = []
        self._snippet_parts = []


class DuckDuckGoLiteHTMLParser(HTMLParser):
    """Parser for lite.duckduckgo.com/lite/ — a simple table layout where result
    titles use <a class="result-link"> and snippets use <td class="result-snippet">."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._current: _PartialResult | None = None
        self._collecting_title = False
        self._collecting_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())

        if tag == "a" and "result-link" in classes:
            self._flush_current()
            self._current = _PartialResult(url=normalize_duckduckgo_url(attr_map.get("href", "")))
            self._collecting_title = True
            self._title_parts = []
            return

        if self._current is not None and tag == "td" and "result-snippet" in classes:
            self._collecting_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._collecting_title:
            self._title_parts.append(data)
        if self._collecting_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._collecting_title and self._current is not None:
            self._current.title = normalize_text(" ".join(self._title_parts))
            self._collecting_title = False
            return

        if self._collecting_snippet and tag == "td" and self._current is not None:
            self._current.snippet = normalize_text(" ".join(self._snippet_parts))
            self._collecting_snippet = False
            self._flush_current()

    def _flush_current(self) -> None:
        if self._current is None:
            return
        if self._current.title and safe_result_url(self._current.url):
            self.results.append(
                SearchResult(
                    title=self._current.title[:300],
                    url=self._current.url,
                    snippet=self._current.snippet[:1000],
                    source="duckduckgo",
                    category="general",
                )
            )
        self._current = None
        self._title_parts = []
        self._snippet_parts = []


class MojeekHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._current: _PartialResult | None = None
        self._collecting_title = False
        self._collecting_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())

        if tag == "a" and "title" in classes:
            self._flush_current()
            self._current = _PartialResult(url=attr_map.get("href", ""))
            self._collecting_title = True
            self._title_parts = []
            return

        if self._current is not None and tag == "p" and "s" in classes:
            self._collecting_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._collecting_title:
            self._title_parts.append(data)
        if self._collecting_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._collecting_title and self._current is not None:
            self._current.title = normalize_text(" ".join(self._title_parts))
            self._collecting_title = False
            return

        if tag == "p" and self._collecting_snippet and self._current is not None:
            self._current.snippet = normalize_text(" ".join(self._snippet_parts))
            self._collecting_snippet = False
            self._flush_current()

    def _flush_current(self) -> None:
        if self._current is None:
            return
        if self._current.title and safe_result_url(self._current.url):
            self.results.append(
                SearchResult(
                    title=self._current.title[:300],
                    url=self._current.url,
                    snippet=self._current.snippet[:1000],
                    source="mojeek",
                    category="general",
                )
            )
        self._current = None
        self._title_parts = []
        self._snippet_parts = []


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def normalize_duckduckgo_url(url: str) -> str:
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return url
