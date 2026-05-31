from __future__ import annotations

import json
import ipaddress
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import WebSearchConfig


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
        return "No search results returned."
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
