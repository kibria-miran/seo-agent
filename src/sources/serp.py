"""Keyless SERP evidence via DuckDuckGo's HTML endpoint (D-3).

We parse the lightweight HTML page rather than depend on an undocumented
JSON API. Every block is parsed defensively; anything unexpected is skipped,
never guessed at. Titles and snippets are untrusted text and go through the
shared scrub in ``Source.collect``.

DuckDuckGo wraps outbound links as ``https://duckduckgo.com/l/?uddg=<url>``;
we decode that parameter so domain attribution and dedupe work on the real
target.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup

from src.models import SerpResult
from src.security import strip_html
from src.sources import fetch
from src.sources.base import Source, SourceError

SERP_URL = "https://html.duckduckgo.com/html/"
MAX_RESULTS = 10

class SerpSource(Source):
    """Top organic results for a query, ranked 1..N."""

    name = "serp"

    def fetch(self, query: str) -> Sequence[Mapping[str, Any]]:
        url = f"{SERP_URL}?{urlencode({'q': query})}"
        try:
            body = fetch.http_get(url)
        except fetch.FetchError as exc:
            raise SourceError(f"serp failed for {query!r}: {exc}") from exc
        soup = BeautifulSoup(body, "lxml")
        items: list[dict[str, Any]] = []
        for block in soup.select(".result"):
            if "result--ad" in (block.get("class") or []):
                continue
            anchor = block.select_one("a.result__a")
            if anchor is None:
                continue
            target = _unwrap_redirect(str(anchor.get("href", "")))
            if not target:
                continue
            title = strip_html(anchor.get_text(" ", strip=True))
            snippet_node = block.select_one(".result__snippet")
            snippet = (
                strip_html(snippet_node.get_text(" ", strip=True)) if snippet_node else ""
            )
            items.append(
                {
                    "query": query,
                    "rank": len(items) + 1,
                    "url": target,
                    "title": title,
                    "snippet": snippet,
                }
            )
            if len(items) >= MAX_RESULTS:
                break
        return items

    @staticmethod
    def to_serp_results(items: Sequence[Mapping[str, Any]]) -> list[SerpResult]:
        results = []
        for item in items:
            try:
                results.append(
                    SerpResult(
                        query=str(item.get("query", "")),
                        rank=int(item.get("rank", 0)),
                        url=str(item.get("url", "")),
                        title=str(item.get("title", "")),
                        snippet=str(item.get("snippet", "")),
                    )
                )
            except (TypeError, ValueError):
                # A malformed cached row must not crash the run; it is dropped.
                continue
        return sorted(results, key=lambda item: (item.query, item.rank, item.url))


def _unwrap_redirect(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in (parsed.hostname or "") and parsed.path.startswith("/l/"):
        # parse_qs performs exactly one level of percent-decoding — correct for
        # uddg, which carries a fully encoded target URL.
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target if target.startswith(("http://", "https://")) else ""
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        return href
    return ""


__all__ = ["MAX_RESULTS", "SERP_URL", "SerpSource"]
