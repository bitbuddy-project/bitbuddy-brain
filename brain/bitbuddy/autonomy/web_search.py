from __future__ import annotations

import json
import ipaddress
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from ..config import WebSearchConfig

# A real browser User-Agent. Some sites (and DuckDuckGo) serve empty/challenge
# pages to obvious bots, so we present as a normal desktop browser.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = "searxng"
    category: str = "general"
    image_url: str = ""
    thumbnail_url: str = ""


def safe_web_search(query: str, config: WebSearchConfig, category: str = "general") -> list[SearchResult]:
    clean_query = " ".join(query.split())
    clean_category = normalize_search_category(category)
    if not config.enabled:
        raise ValueError("Web search is disabled.")
    if config.provider != "searxng":
        raise ValueError("Only SearxNG web search is supported right now.")
    if not clean_query:
        raise ValueError("Search query is required.")

    params = urllib.parse.urlencode({"q": clean_query, "format": "json", "categories": clean_category})
    url = f"{config.url.rstrip('/')}/search?{params}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "BitBuddy/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(1_000_000)
    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionRefusedError) or "[Errno 111]" in str(e):
            raise ValueError(
                f"Web search failed: Connection refused to SearxNG at {config.url}. "
                "When started with `bitbuddy serve`, BitBuddy should run its managed local "
                "SearxNG-compatible search backend automatically. Check the BitBuddy server "
                "activity log or update 'autonomy.web_search.url' in config.yaml."
            ) from e
        raise ValueError(f"Web search failed: {e}") from e
    except Exception as e:
        raise ValueError(f"Web search failed: {e}") from e

    data = json.loads(raw.decode("utf-8"))
    return parse_searxng_results(data, limit=config.max_results, category=clean_category)


def normalize_search_category(category: str) -> str:
    clean = str(category or "general").strip().lower()
    if clean in {"image", "images", "photo", "photos", "picture", "pictures"}:
        return "images"
    return "general"


def parse_searxng_results(data: dict[str, Any], limit: int = 5, category: str = "general") -> list[SearchResult]:
    clean_category = normalize_search_category(category)
    rows = data.get("results") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    results: list[SearchResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        snippet = str(row.get("content") or row.get("snippet") or "").strip()
        result_category = normalize_search_category(str(row.get("category") or clean_category))
        image_url = str(row.get("img_src") or row.get("image") or "").strip()
        thumbnail_url = str(row.get("thumbnail_src") or row.get("thumbnail") or "").strip()
        if not title or not safe_result_url(url):
            continue
        if image_url and not safe_result_url(image_url):
            image_url = ""
        if thumbnail_url and not safe_result_url(thumbnail_url):
            thumbnail_url = ""
        results.append(
            SearchResult(
                title=title[:300],
                url=url,
                snippet=snippet[:1000],
                category=result_category,
                image_url=image_url,
                thumbnail_url=thumbnail_url,
            )
        )
        if len(results) >= limit:
            break
    return results


def safe_result_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast:
        return False
    return True


def search_results_to_text(results: list[SearchResult]) -> str:
    if not results:
        return (
            "No search results returned. The local search backend may have been rate-limited "
            "or blocked. Try a simpler query, or call web_fetch with a specific URL to read a page directly."
        )
    lines: list[str] = []
    for index, result in enumerate(results, 1):
        lines.append(f"{index}. {result.title}")
        lines.append(f"   URL: {result.url}")
        if result.category == "images":
            if result.image_url:
                lines.append(f"   Image URL: {result.image_url}")
            if result.thumbnail_url:
                lines.append(f"   Thumbnail URL: {result.thumbnail_url}")
        if result.snippet:
            lines.append(f"   Snippet: {result.snippet}")
    return "\n".join(lines)


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    text: str
    content_type: str


def safe_web_fetch(url: str, *, max_chars: int = 12000, timeout: int = 12) -> FetchedPage:
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("A URL is required.")
    if "://" not in clean_url:
        clean_url = f"https://{clean_url}"
    if not safe_result_url(clean_url):
        raise ValueError(
            f"Refusing to fetch {clean_url!r}: only public http(s) URLs are allowed "
            "(local, loopback, and private addresses are blocked)."
        )

    request = urllib.request.Request(
        clean_url,
        headers={
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": BROWSER_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            raw = response.read(1_500_000)
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        raise ValueError(f"Web fetch failed: {clean_url} returned HTTP {e.code} {e.reason}.") from e
    except urllib.error.URLError as e:
        raise ValueError(f"Web fetch failed: could not reach {clean_url} ({e.reason}).") from e
    except Exception as e:
        raise ValueError(f"Web fetch failed: {e}") from e

    body = raw.decode(charset, errors="replace")

    if content_type in {"text/html", "application/xhtml+xml"} or (not content_type and "<html" in body[:2000].lower()):
        title, text = html_to_text(body)
    else:
        title, text = "", " ".join(body.split())

    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…[truncated]"

    return FetchedPage(url=clean_url, title=title[:300], text=text, content_type=content_type or "text/plain")


def html_to_text(html: str) -> tuple[str, str]:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    text = " ".join(parser.text_parts)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return parser.title.strip(), text.strip()


class _HTMLTextExtractor(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
    _BLOCK_TAGS = {
        "p", "br", "div", "section", "article", "header", "footer", "li", "ul", "ol",
        "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title += data
            return
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)


def fetched_page_to_text(page: FetchedPage) -> str:
    lines = [f"URL: {page.url}"]
    if page.title:
        lines.append(f"Title: {page.title}")
    lines.append("")
    lines.append(page.text or "(no readable text extracted)")
    return "\n".join(lines)
