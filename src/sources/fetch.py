"""Polite HTTP fetching and page extraction (D-5, D-15).

All live HTTP goes through ``http_get``. It performs a GET (never HEAD, per
D-15) with the honest UA from config, enforces the shared per-host delay,
caps the response size and raises ``FetchError`` on anything that is not a
2xx text response. ``fetch_page`` additionally honours ``robots.txt`` and
returns *cleaned* text; the raw HTML is untrusted and never leaves this
module for anything other than markup-aware parsing inside ``src/sources``.
"""

from __future__ import annotations

import time
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests

from src import clock, config
from src.security import strip_html

MAX_PAGE_BYTES = 1_000_000  # 1 MB; audit/compare never needs more
_ROBOTS_PREFIX = "robots.txt"

USER_AGENT = config.USER_AGENT

# host -> epoch seconds of last request. Module-level on purpose: politeness
# is a per-process constraint, not a per-call one.
_LAST_REQUEST: dict[str, float] = {}
_ROBOTS: dict[str, robotparser.RobotFileParser | None] = {}


class FetchError(RuntimeError):
    """Raised when a page cannot be fetched, is blocked or is too large."""


_module_state: dict[str, int] = {"fetches": 0}


def reset_state() -> None:
    """Clear the per-process throttle, robots memo and fetch counter."""

    _LAST_REQUEST.clear()
    _ROBOTS.clear()
    _module_state["fetches"] = 0


def fetch_count() -> int:
    """HTTP GETs performed by this process since the last ``reset_state()``."""

    return _module_state["fetches"]


def throttle(host: str, *, delay: float | None = None) -> None:
    """Sleep until ``delay`` seconds have passed since the last request to ``host``."""

    wait = config.HOST_DELAY_SECONDS if delay is None else delay
    last = _LAST_REQUEST.get(host)
    now = clock.now().timestamp()
    if last is not None and now - last < wait:
        time.sleep(wait - (now - last))
    _LAST_REQUEST[host] = clock.now().timestamp()


def http_get(
    url: str,
    *,
    respect_robots: bool = False,
    timeout: float | None = None,
    delay: float | None = None,
    user_agent: str | None = None,
) -> bytes:
    """GET ``url`` with the honest UA and shared throttle. Returns the body.

    ``respect_robots=True`` checks the host's robots.txt first (page crawls).
    Search/API endpoints pass ``False``; they are not page crawls but are
    still throttled and GET-only. ``user_agent`` overrides the default UA
    for hosts that require a browser-like identity (e.g. DuckDuckGo HTML).
    """

    host = urlparse(url).hostname or ""
    if respect_robots and not _robots_allowed(url):
        raise FetchError(f"robots.txt disallows fetching {url}")
    throttle(host, delay=delay)
    _module_state["fetches"] += 1
    ua = user_agent if user_agent is not None else USER_AGENT
    try:
        response = requests.get(
            url,
            headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5"},
            timeout=timeout or config.HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise FetchError(f"fetch failed for {url}: {exc}") from exc
    if response.status_code >= 400:
        raise FetchError(f"HTTP {response.status_code} for {url}")
    body = response.content
    if len(body) > MAX_PAGE_BYTES:
        raise FetchError(f"response too large for {url}: {len(body)} bytes")
    return body


def fetch_text(url: str) -> str:
    """GET a text resource and decode it (UTF-8, replacement on errors)."""

    return http_get(url, respect_robots=True).decode("utf-8", errors="replace")


def fetch_page(url: str, *, timeout: float | None = None) -> str:
    """GET a page and return its cleaned text.

    Comments, ``data-*`` attributes, scripts, styles and tags are stripped and
    entities are decoded; the result is untrusted text suitable only for being
    run through :func:`src.security.scan`.
    """

    body = http_get(url, respect_robots=True, timeout=timeout)
    return strip_html(body.decode("utf-8", errors="replace"))


def _robots_allowed(url: str) -> bool:
    """Per-host robots.txt check, memoised for the process.

    An unreachable or unreadable robots.txt is treated as allow (RFC 9309
    only binds when a valid file exists). A parse failure is treated the same
    way; blocking a paying crawl because of a broken robots.txt would hide
    real audit results.
    """

    host = urlparse(url).hostname or ""
    if host in _ROBOTS:
        parser = _ROBOTS[host]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    robots_url = urljoin(url, "/" + _ROBOTS_PREFIX)
    parser: robotparser.RobotFileParser | None = None
    try:
        throttle(host)
        _module_state["fetches"] += 1
        response = requests.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code < 400 and response.content:
            parser = robotparser.RobotFileParser()
            parser.parse(response.text.splitlines())
    except requests.RequestException:
        parser = None
    _ROBOTS[host] = parser
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


__all__ = [
    "MAX_PAGE_BYTES",
    "USER_AGENT",
    "FetchError",
    "fetch_count",
    "fetch_page",
    "fetch_text",
    "http_get",
    "reset_state",
    "throttle",
]
