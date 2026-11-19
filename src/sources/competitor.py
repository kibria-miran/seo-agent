"""Competitor page discovery and coverage evidence (Phase 3, D-3, D-5).

Discovery is keyless: a DuckDuckGo HTML ``site:`` query per (seed, competitor)
pair finds the competitor's page for a term we care about. Each domain keeps
at most ``MAX_COMP_PAGES`` pages (D-5); total discovery queries are capped by
``MAX_SERP_QUERIES`` and the run's fetch counter is hard-stopped at
``MAX_FETCHES``.

Fetched markup is untrusted. A page whose title, meta description or
headings carry an injection marker is dropped whole and logged as
``injection_attempt``; never partially trusted (D-4).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src import config
from src.models import CompetitorPage
from src.security import find_injection, strip_html
from src.sources import fetch
from src.sources.base import SourceError
from src.sources.serp import SerpSource
from src.sources.suggest import seed_terms
from src.store import Store
from src.trace import TraceWriter

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


class CompetitorPageError(SourceError):
    """A competitor page could not be fetched or parsed."""


def competitor_seeds(profile: Any) -> list[str]:
    """Discovery seeds: money-page keywords + target keywords."""

    return seed_terms(profile)


def _host_matches(domain: str, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    bare = domain.lower().removeprefix("www.")
    return host == bare or host.endswith("." + bare)


def _strip_fragment(url: str) -> str:
    # Fragments never change document identity (they only affect client-side navigation).
    base, _, _ = url.partition("#")
    return base


def _schema_types(soup: BeautifulSoup) -> list[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            kind = node.get("@type")
            if isinstance(kind, str):
                found.add(kind)
            elif isinstance(kind, list):
                found.update(item for item in kind if isinstance(item, str))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue
    return sorted(found)


def parse_competitor_page(html: str | bytes, url: str) -> CompetitorPage:
    """Parse one competitor page. Raises ``CompetitorPageError`` on injection."""

    soup = BeautifulSoup(html, "lxml")
    for node in list(soup(["script", "style"])):
        # JSON-LD is read below (schema types); executable scripts are not data.
        if not (node.string and "ld+json" in str(node.get("type", ""))):
            node.decompose()

    title = strip_html(soup.title.get_text(" ", strip=True)) if soup.title else ""
    meta_node = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    meta_description = ""
    if meta_node is not None:
        meta_description = strip_html(str(meta_node.get("content", "")))

    h_tags: dict[str, list[str]] = {}
    for tag in _HEADING_TAGS:
        values = [strip_html(node.get_text(" ", strip=True)) for node in soup.select(tag)]
        values = [value for value in values if value]
        if values:
            h_tags[tag] = values

    text_parts = [title, meta_description]
    for values in h_tags.values():
        text_parts.extend(values)
    joined = " ".join(text_parts)
    if find_injection(joined):
        raise CompetitorPageError(f"injection markers found in page text: {url}")

    word_count = len(soup.get_text(" ", strip=True).split())
    domain = urlparse(url).hostname or ""
    return CompetitorPage(
        domain=domain.lower().removeprefix("www."),
        url=url,
        title=title,
        meta_description=meta_description,
        h_tags=h_tags,
        word_count=word_count,
        schema_types=_schema_types(soup),
    )


def fetch_competitor_page(url: str) -> CompetitorPage:
    """Fetch and parse one competitor page (robots-respected, GET-only)."""

    body = fetch.http_get(url, respect_robots=True)
    return parse_competitor_page(body, url)


def _cached_page(store: Store, url: str) -> CompetitorPage | None:
    payload = store.get_cache(f"competitor_page|{url}")
    if not isinstance(payload, dict):
        return None
    try:
        return CompetitorPage(**payload)
    except (ValueError, TypeError):
        return None


def mine_competitors(
    profile: Any,
    *,
    store: Store,
    trace: TraceWriter | None = None,
    max_per_domain: int | None = None,
    max_queries: int | None = None,
) -> list[CompetitorPage]:
    """Discover and parse up to ``max_per_domain`` pages per competitor.

    Network failures and robots blocks skip the page; injection hits drop the
    page and are logged. Everything degrades to an empty list, never a crash.
    """

    per_domain = max_per_domain if max_per_domain is not None else config.MAX_COMP_PAGES
    query_cap = max_queries if max_queries is not None else config.MAX_SERP_QUERIES
    seeds = competitor_seeds(profile)
    serp = SerpSource()

    urls_by_domain: dict[str, list[str]] = {domain: [] for domain in profile.competitors}
    seen_urls: set[str] = set()
    queries = 0
    for seed in seeds:
        if queries >= query_cap:
            break
        for domain in profile.competitors:
            if queries >= query_cap:
                break
            if fetch.fetch_count() >= config.MAX_FETCHES:
                break
            try:
                result = serp.collect(f"site:{domain} {seed}", store=store, trace=trace)
            except SourceError:
                continue
            queries += 1
            for item in result.items:
                url = _strip_fragment(str(item.get("url", "")))
                if not url or not _host_matches(domain, url):
                    continue
                bucket = urls_by_domain[domain]
                if url not in seen_urls and url not in bucket and len(bucket) < per_domain:
                    bucket.append(url)
                    seen_urls.add(url)

    # Fallback: DDG ``site:`` discovery can be blocked (anomaly challenge) or
    # return nothing. When a competitor domain yielded no discovered URLs,
    # build likely money-page URLs from the profile's own money_pages slugs
    # and try them directly. Network/robots/injection failures are skipped so
    # discovery still degrades gracefully.
    for domain in profile.competitors:
        if urls_by_domain[domain]:
            continue
        for path in profile.money_pages:
            if len(urls_by_domain[domain]) >= per_domain:
                break
            url = f"https://{domain}{path}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            urls_by_domain[domain].append(url)

    pages: list[CompetitorPage] = []
    for domain in sorted(urls_by_domain):
        for url in sorted(urls_by_domain[domain]):
            cached = _cached_page(store, url)
            if cached is not None:
                pages.append(cached)
                continue
            if fetch.fetch_count() >= config.MAX_FETCHES:
                if trace is not None:
                    trace.emit(step="sources", tool="competitor", args={},
                               source="net", status="skipped", kind="budget",
                               reason="max_fetches")
                return pages
            try:
                page = fetch_competitor_page(url)
            except fetch.FetchError:
                continue
            except CompetitorPageError:
                if trace is not None:
                    trace.emit(step="sources", tool="competitor", args={"url": url},
                               source="net", status="dropped", kind="injection_attempt")
                continue
            store.set_cache(f"competitor_page|{url}", page.model_dump(mode="json"))
            pages.append(page)
    return pages


__all__ = [
    "CompetitorPageError",
    "competitor_seeds",
    "fetch_competitor_page",
    "mine_competitors",
    "parse_competitor_page",
]
