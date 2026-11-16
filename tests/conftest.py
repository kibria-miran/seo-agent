"""Shared test fixtures and factories.

Process gate (D-11): this file must import cleanly before any ``agent.py``
line exists. ``tests/test_smoke.py`` is deliberately trivial and proves it.

Two rules that are easy to get wrong
------------------------------------
* A proposer-failure test must stage **TWO bad responses**, because the agent
  retries exactly once before falling back to the deterministic template
  (D-12).
* A loop-guard test must stage the **SAME (tool, args) twice consecutively**.
  Non-consecutive repeats with new args must be permitted (I-4); do not write
  a test that bans all repeats.

All factories below default **every** field. Pass ``**overrides`` to change
one thing per test and keep the rest of the world fixed.
"""

from __future__ import annotations

import builtins
import contextlib
import copy
import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import pytest

from src import clock, config
from src.models import (
    AuditSnapshot,
    BacklogItem,
    Cluster,
    CompetitorPage,
    Gap,
    GapType,
    Intent,
    Keyword,
    PageData,
    RunReport,
    SEOIssue,
    SerpResult,
    Severity,
    SiteProfile,
)


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


class FakeLLM:
    """Pop one canned response per call.

    An empty response list is a test bug (the agent asked for something the
    test did not stage), so it calls ``pytest.fail`` instead of returning
    ``None``. A response may be an exception instance, which is raised.
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses: list[Any] = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.count = 0

    def __call__(self, messages: Any, *args: Any, **kwargs: Any) -> str:
        if not self.responses:
            pytest.fail(
                "FakeLLM ran out of responses: stage one more response, or use "
                "--no-llm for the deterministic path",
                pytrace=False,
            )
        response = self.responses.pop(0)
        self.count += 1
        self.calls.append(
            {
                "messages": copy.deepcopy(messages),
                "args": args,
                "kwargs": kwargs,
            }
        )
        if isinstance(response, BaseException):
            raise response
        return response

    # Convenient aliases: production code may call llm.chat(...) or llm(...).
    chat = __call__

    @property
    def last(self) -> dict[str, Any] | None:
        return self.calls[-1] if self.calls else None

    def reset(self, responses: list[Any] | None = None) -> None:
        if responses is not None:
            self.responses = list(responses)
        self.calls.clear()
        self.count = 0


# ---------------------------------------------------------------------------
# Model factories
# ---------------------------------------------------------------------------


def make_issue(**overrides: Any) -> SEOIssue:
    data: dict[str, Any] = {
        "page_url": "https://clearpath-mortgage.co.uk/remortgage",
        "issue_type": "Duplicate Title",
        "severity": Severity.WARNING,
        "current_value": "Remortgage Advice | ClearPath",
        "suggestion": "Make the title unique and include the primary keyword.",
    }
    data.update(overrides)
    return SEOIssue(**data)


def make_page(**overrides: Any) -> PageData:
    data: dict[str, Any] = {
        "url": "https://clearpath-mortgage.co.uk/",
        "status_code": 200,
        "title": "Free Mortgage Advice from ClearPath",
        "meta_description": "Whole-of-market mortgage advice for UK borrowers.",
        "h1_tags": ["Free mortgage advice"],
        "h2_tags": ["How we help"],
        "h3_tags": [],
        "h1_count": 1,
        "word_count": 850,
        "page_score": 95.0,
        "response_time_ms": 180.0,
        "schema_types": ["FinancialService"],
        "issues": [],
        "final_url": None,
    }
    data.update(overrides)
    return PageData(**data)


def make_audit(**overrides: Any) -> AuditSnapshot:
    pages = overrides.pop("pages", None)
    issues = overrides.pop("issues", None)
    if pages is None:
        pages = [make_page()]
    if issues is None:
        issues = [issue for page in pages for issue in page.issues]

    site_score = overrides.pop("site_score", None)
    if site_score is None:
        site_score = (
            round(sum(page.page_score for page in pages) / len(pages), 1) if pages else 0.0
        )
    grade = overrides.pop("grade", None) or config.grade_for(site_score)

    data: dict[str, Any] = {
        "url": "https://clearpath-mortgage.co.uk",
        "site_score": site_score,
        "grade": grade,
        "pages_crawled": len(pages),
        "total_issues": len(issues),
        "critical_count": sum(i.severity == Severity.CRITICAL for i in issues),
        "warning_count": sum(i.severity == Severity.WARNING for i in issues),
        "info_count": sum(i.severity == Severity.INFO for i in issues),
        "pages": pages,
        "issues": issues,
        "audit_date": None,
        "extras": {},
    }
    data.update(overrides)
    return AuditSnapshot(**data)


def make_serp_result(**overrides: Any) -> SerpResult:
    data: dict[str, Any] = {
        "query": "free mortgage advice",
        "rank": 1,
        "url": "https://www.moneysavingexpert.com/mortgages/free-mortgage-advice/",
        "title": "Free Mortgage Advice",
        "snippet": "How to get free mortgage advice in the UK.",
        "domain": "moneysavingexpert.com",
    }
    data.update(overrides)
    return SerpResult(**data)


def make_competitor_page(**overrides: Any) -> CompetitorPage:
    data: dict[str, Any] = {
        "domain": "moneysavingexpert.com",
        "url": "https://www.moneysavingexpert.com/mortgages/free-mortgage-advice/",
        "title": "Free Mortgage Advice",
        "meta_description": "How to get free mortgage advice in the UK.",
        "h_tags": {"h1": ["Free mortgage advice"], "h2": ["Brokers", "Fees"]},
        "word_count": 1450,
        "schema_types": ["FAQPage"],
    }
    data.update(overrides)
    return CompetitorPage(**data)


def make_keyword(**overrides: Any) -> Keyword:
    data: dict[str, Any] = {
        "keyword": "remortgage advice",
        "source": "suggest",
        "cluster_id": "c1",
        "intent": Intent.INFORMATIONAL,
        "city": None,
    }
    data.update(overrides)
    return Keyword(**data)


def make_cluster(**overrides: Any) -> Cluster:
    data: dict[str, Any] = {
        "cluster_id": "c1",
        "label": "Remortgage advice",
        "head_term": "remortgage advice",
        "keywords": ["remortgage advice", "remortgage help", "remortgage guide"],
    }
    data.update(overrides)
    return Cluster(**data)


def make_gap(**overrides: Any) -> Gap:
    data: dict[str, Any] = {
        "keyword": "remortgage advice",
        "cluster_id": "c1",
        "gap_type": GapType.NO_PAGE,
        "evidence": {"pages": [], "serp": []},
        "sources": ["suggest"],
        "target": None,
    }
    data.update(overrides)
    return Gap(**data)


def make_backlog_item(**overrides: Any) -> BacklogItem:
    data: dict[str, Any] = {
        "item_id": "BL-0001",
        "kind": "create_page",
        "target": "remortgage advice",
        "priority": 1.0,
        "effort": 3,
        "impact": 2,
        "status": "open",
        "confidence": 0.5,
        "evidence": {},
        "title": "Create a page targeting 'remortgage advice'",
        "gap_type": "NO_PAGE",
    }
    data.update(overrides)
    return BacklogItem(**data)


def make_profile(**overrides: Any) -> SiteProfile:
    data: dict[str, Any] = {
        "domain": "https://clearpath-mortgage.co.uk",
        "money_pages": ["/", "/free-mortgage-advice", "/remortgage"],
        "target_keywords": ["free mortgage advice", "remortgage calculator"],
        "competitors": ["moneysavingexpert.com", "habito.com"],
        "cities": ["London", "Manchester"],
        "fca_firm_ref": "123456",
    }
    data.update(overrides)
    return SiteProfile(**data)


def make_run_report(**overrides: Any) -> RunReport:
    data: dict[str, Any] = {
        "run_id": "run-20261116T090000Z",
        "status": "ok",
        "site_score": 82.4,
        "grade": "B",
        "generated_at": "2026-11-16T09:00:00+00:00",
        "report_markdown": "# SEO report\n",
        "backlog": [],
        "diff": {},
        "budgets": {},
    }
    data.update(overrides)
    return RunReport(**data)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


@pytest.fixture
def inject_clock(monkeypatch: pytest.MonkeyPatch):
    """Return ``inject_clock(start, step=None)`` to pin ``clock.now``.

    ``now`` advances by ``step`` on every call. ``step`` may be seconds or a
    ``timedelta``. All production code must call ``clock.now()`` rather than
    importing ``datetime`` directly for this to work (D-10).
    """

    def _inject(start: datetime | str, step: float | timedelta | None = None):
        if isinstance(start, str):
            base = datetime.fromisoformat(start)
        else:
            base = start
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        tick = timedelta(0)
        if step is not None:
            tick = step if isinstance(step, timedelta) else timedelta(seconds=float(step))
        counter = itertools.count()

        def _now() -> datetime:
            return base + (tick * next(counter))

        monkeypatch.setattr(clock, "now", _now)
        return _now

    return _inject


# ---------------------------------------------------------------------------
# Network / audit injection
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_fetcher(monkeypatch: pytest.MonkeyPatch):
    """Return ``fake_fetcher({url: html})``; fast tests never hit the network."""

    def _install(pages: dict[str, str]):
        try:
            from src.sources import fetch as fetch_module
        except Exception as exc:  # pragma: no cover - import error is the failure
            pytest.fail(f"cannot import src.sources.fetch: {exc}", pytrace=False)

        calls: list[str] = []

        def _fetch_page(url: str, *args: Any, **kwargs: Any) -> str:
            calls.append(url)
            if url not in pages:
                raise fetch_module.FetchError(f"no fake page staged for {url}")
            return pages[url]

        _fetch_page.calls = calls  # type: ignore[attr-defined]
        monkeypatch.setattr(fetch_module, "fetch_page", _fetch_page, raising=False)
        monkeypatch.setattr(fetch_module, "fetch", _fetch_page, raising=False)
        return _fetch_page

    return _install


@pytest.fixture
def inject_fixture(monkeypatch: pytest.MonkeyPatch):
    """Point the audit adapter at a fixture JSON, bypassing the network (I-15)."""

    def _inject(path: str | Path):
        from src import audit_adapter

        candidate = Path(path)
        if not candidate.is_absolute() and not candidate.exists():
            candidate = config.FIXTURES_DIR / candidate
        if not candidate.exists():
            pytest.fail(f"fixture not found: {candidate}", pytrace=False)
        monkeypatch.setattr(audit_adapter, "DEFAULT_FIXTURE_PATH", candidate)
        return candidate

    return _inject


# ---------------------------------------------------------------------------
# Safety helpers (D-15 / I-19)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def assert_write_paths_under(
    tmpdir: str | Path,
    allowed: tuple[str, ...] = ("out/", "logs/"),
) -> Iterator[list[str]]:
    """Fail if anything writes outside ``tmpdir/<allowed>``.

    Patches ``builtins.open``, ``Path.open``, ``Path.write_text`` and
    ``Path.write_bytes``. Reads pass through untouched. Yields the list of
    paths that were written so a test can assert the expected outputs exist.
    """

    root = Path(tmpdir).resolve()
    allowed_roots = tuple(allowed)
    written: list[str] = []
    real_builtin_open = builtins.open
    real_path_open = Path.open
    real_write_text = Path.write_text
    real_write_bytes = Path.write_bytes

    def _check(target: Any) -> None:
        path = Path(target).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            pytest.fail(
                f"write outside the tmpdir: {path} (root={root})",
                pytrace=False,
            )
        if allowed_roots:
            head = relative.parts[0] if relative.parts else ""
            if not any(head == item.rstrip("/") for item in allowed_roots):
                pytest.fail(
                    f"write outside allowed roots {allowed_roots}: {relative}",
                    pytrace=False,
                )
        # Path.write_text() delegates to Path.open(), which is also guarded.
        # Collapse the nested duplicate so the log reads like user-level writes.
        if not written or written[-1] != str(path):
            written.append(str(path))

    def _is_write(mode: str) -> bool:
        return any(flag in mode for flag in ("w", "a", "x", "+"))

    def guarded_builtin_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any):
        if _is_write(mode):
            _check(file)
        return real_builtin_open(file, mode, *args, **kwargs)

    def guarded_path_open(self: Path, mode: str = "r", *args: Any, **kwargs: Any):
        if _is_write(mode):
            _check(self)
        return real_path_open(self, mode, *args, **kwargs)

    def guarded_write_text(self: Path, *args: Any, **kwargs: Any):
        _check(self)
        return real_write_text(self, *args, **kwargs)

    def guarded_write_bytes(self: Path, *args: Any, **kwargs: Any):
        _check(self)
        return real_write_bytes(self, *args, **kwargs)

    builtins.open = guarded_builtin_open  # type: ignore[assignment]
    Path.open = guarded_path_open  # type: ignore[assignment]
    Path.write_text = guarded_write_text  # type: ignore[assignment]
    Path.write_bytes = guarded_write_bytes  # type: ignore[assignment]
    try:
        yield written
    finally:
        builtins.open = real_builtin_open  # type: ignore[assignment]
        Path.open = real_path_open  # type: ignore[assignment]
        Path.write_text = real_write_text  # type: ignore[assignment]
        Path.write_bytes = real_write_bytes  # type: ignore[assignment]


@contextlib.contextmanager
def fake_http_get_only(
    allowed_llm_hosts: set[str] | None = None,
) -> Iterator[list[tuple[str, str]]]:
    """Assert every outbound HTTP call is GET except the LLM POST (D-15).

    HEAD is intentionally not allowed: our broken-link checker uses GET
    (DECISIONS.md R-3). ``requests.get``/``post``/``head`` all end up in
    ``requests.sessions.Session.request``, so patching that one method covers
    the whole requests API.
    """

    import requests

    llm_host = urlparse(config.NIM_BASE_URL).hostname or ""
    allowed_hosts = {
        llm_host,
        "integrate.api.nvidia.com",
        "api.openai.com",
        "localhost",
        "127.0.0.1",
    }
    if allowed_llm_hosts:
        allowed_hosts.update(allowed_llm_hosts)

    calls: list[tuple[str, str]] = []
    real_request = requests.sessions.Session.request

    def guarded_request(self, method: str, url: str, *args: Any, **kwargs: Any):
        upper = str(method).upper()
        host = urlparse(url).hostname or ""
        calls.append((upper, url))
        if upper == "POST" and host in allowed_hosts:
            return real_request(self, method, url, *args, **kwargs)
        if upper != "GET":
            raise AssertionError(
                f"HTTP method {upper} is not allowed (D-15): {url}"
            )
        return real_request(self, method, url, *args, **kwargs)

    requests.sessions.Session.request = guarded_request  # type: ignore[assignment]
    try:
        yield calls
    finally:
        requests.sessions.Session.request = real_request  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test fast unless it opts into slow/live."""

    for item in items:
        markers = {marker.name for marker in item.iter_markers()}
        if "slow" not in markers and "live" not in markers:
            item.add_marker(pytest.mark.fast)
