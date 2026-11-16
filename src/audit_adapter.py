"""Adapter around the vendored seoextract audit layer (D-1, section 8.1).

This is the ONLY module allowed to import seoextract. It translates upstream
Pydantic objects into our own models so an upstream rename breaks exactly one
file and its capability-probe test.

The real 0.3.0 API (verified against the vendored commit) is:

    from seoextract import SEOExtract
    from seoextract.models import AuditResult, PageData, SEOIssue, Severity

The original draft assumed all four names were exported from the package root
and that the field was ``meta_desc``. That was wrong; see PROVENANCE.md and
DECISIONS.md R-1.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src import config
from src.models import AuditSnapshot, Severity
from src.models import PageData as OurPageData
from src.models import SEOIssue as OurSEOIssue

REQUIRED_MODEL_NAMES: tuple[str, ...] = ("AuditResult", "PageData", "SEOIssue")
REQUIRED_CORE_ATTR = "SEOExtract.audit"

# Tests set this through the ``inject_fixture`` fixture. None means network.
DEFAULT_FIXTURE_PATH: Path | str | None = None


class AuditFixtureError(ValueError):
    """Raised when a fixture file is missing or not a valid audit document."""


def _ensure_vendor_on_path() -> None:
    vendor = str(config.SEOEXTRACT_DIR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def probe_capabilities(models_module: Any, core_module: Any = None) -> None:
    """Raise ``ImportError`` naming every missing seoextract symbol.

    ``core_module`` may be the package or the ``seoextract.core`` module. We
    accept either shape because that is what a future upstream refactor might
    produce.
    """

    if core_module is None:  # pragma: no cover - normal path supplies it
        _ensure_vendor_on_path()
        from seoextract import core as core_module  # type: ignore[no-redef]

    missing: list[str] = [name for name in REQUIRED_MODEL_NAMES if not hasattr(models_module, name)]

    extractor = getattr(core_module, "SEOExtract", None)
    if extractor is None and callable(getattr(core_module, "audit", None)):
        # Accept the class itself as well as the module that contains it.
        extractor = core_module
    if extractor is None:
        missing.append("SEOExtract")
    elif not callable(getattr(extractor, "audit", None)):
        missing.append(REQUIRED_CORE_ATTR)

    if missing:
        raise ImportError(
            "seoextract capability probe failed: missing "
            + ", ".join(missing)
            + f" (vendored commit {config.SEOEXTRACT_COMMIT}, expected 0.3.0). "
            "Only src/audit_adapter.py should need changing; see "
            "third_party/PROVENANCE.md."
        )


# ---------------------------------------------------------------------------
# Import the vendored package. A missing checkout must not break fixtures.
# ---------------------------------------------------------------------------

_ensure_vendor_on_path()
SEOEXTRACT_AVAILABLE = False
SEOEXTRACT_IMPORT_ERROR: BaseException | None = None

try:  # pragma: no cover - exercised by the real vendored package
    from seoextract import SEOExtract as _SEOExtract  # type: ignore
    from seoextract import models as _seo_models  # type: ignore

    probe_capabilities(_seo_models, _SEOExtract)
    SEOEXTRACT_AVAILABLE = True
except BaseException as exc:  # noqa: BLE001 - import-time capability probe
    _SEOExtract = None  # type: ignore[assignment]
    _seo_models = None  # type: ignore[assignment]
    SEOEXTRACT_IMPORT_ERROR = exc


# ---------------------------------------------------------------------------
# Runtime politeness wrapper (we do not edit the vendored fork)
# ---------------------------------------------------------------------------

_LAST_CALL: dict[str, float] = {}
_POLITENESS_INSTALLED = False


def _install_politeness() -> None:
    """Give the vendored crawler our honest UA, bot name and 2 s host delay.

    seoextract 0.3.0 ships a browser UA and no delay. Editing the fork is
    forbidden (D-1), so the adapter wraps its ``fetch_page`` at runtime. This
    runs only on the network path.
    """

    global _POLITENESS_INSTALLED
    if _POLITENESS_INSTALLED:
        return
    from seoextract import crawler  # type: ignore

    crawler.HEADERS["User-Agent"] = config.USER_AGENT
    crawler.BOT_NAME = config.APP_NAME
    original = crawler.fetch_page

    def polite_fetch(url: str, session: Any) -> dict[str, Any]:
        host = urlparse(url).hostname or ""
        now = time.monotonic()
        last = _LAST_CALL.get(host)
        if last is not None:
            remaining = config.HOST_DELAY_SECONDS - (now - last)
            if remaining > 0:
                time.sleep(remaining)
        _LAST_CALL[host] = time.monotonic()
        return original(url, session)

    polite_fetch._seo_agent_polite = True  # type: ignore[attr-defined]
    crawler.fetch_page = polite_fetch
    _POLITENESS_INSTALLED = True


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    return {}


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _severity(value: Any) -> Severity:
    raw = getattr(value, "value", value)
    try:
        return Severity(str(raw).upper())
    except ValueError:
        return Severity.INFO


def _issue_from(value: Any) -> OurSEOIssue:
    issue_type = getattr(_get(value, "issue_type", ""), "value", _get(value, "issue_type", ""))
    return OurSEOIssue(
        page_url=str(_get(value, "page_url", "") or ""),
        issue_type=str(issue_type or ""),
        severity=_severity(_get(value, "severity", "INFO")),
        current_value=str(_get(value, "current_value", "") or ""),
        suggestion=str(_get(value, "suggestion", "") or ""),
    )


def _schema_types(value: Any) -> list[str]:
    explicit = _get(value, "schema_types", None)
    if explicit:
        return [str(item) for item in explicit]
    if _get(value, "schema_found", False):
        return ["unknown"]
    return []


def _page_from(value: Any) -> OurPageData:
    meta = _get(value, "meta_description", _get(value, "meta_desc", None))
    h1_tags = list(_get(value, "h1_tags", []) or [])
    h2_tags = list(_get(value, "h2_tags", []) or [])
    h3_tags = list(_get(value, "h3_tags", []) or [])
    issues = [_issue_from(item) for item in (_get(value, "issues", []) or [])]
    h1_count = int(_get(value, "h1_count", 0) or 0)
    if h1_tags and not h1_count:
        h1_count = len(h1_tags)
    return OurPageData(
        url=str(_get(value, "url", "") or ""),
        status_code=int(_get(value, "status_code", 0) or 0),
        title=_get(value, "title", None),
        meta_description=meta,
        h1_tags=h1_tags,
        h2_tags=h2_tags,
        h3_tags=h3_tags,
        h1_count=h1_count,
        word_count=int(_get(value, "word_count", 0) or 0),
        page_score=float(_get(value, "page_score", 0.0) or 0.0),
        response_time_ms=float(_get(value, "response_time_ms", 0.0) or 0.0),
        schema_types=_schema_types(value),
        issues=issues,
        final_url=_get(value, "final_url", None),
    )


def snapshot_from_value(value: Any, url: str | None = None) -> AuditSnapshot:
    """Convert a seoextract result (model, dict or fixture dict) to our model."""

    data = _as_mapping(value) if not isinstance(value, dict) else value
    pages_raw = data.get("pages", []) or []
    pages = [_page_from(page) for page in pages_raw]

    issues_raw = data.get("issues", []) or []
    issues = [_issue_from(issue) for issue in issues_raw]
    if not issues:
        for page in pages:
            issues.extend(page.issues)

    site_url = url or data.get("url") or data.get("domain") or ""
    grade = data.get("grade") or ""

    return AuditSnapshot(
        url=str(site_url),
        site_score=float(data.get("site_score", 0.0) or 0.0),
        grade=str(grade),
        pages_crawled=int(data.get("pages_crawled", len(pages)) or len(pages)),
        total_issues=int(data.get("total_issues", len(issues)) or len(issues)),
        critical_count=int(data.get("critical_count", 0) or 0),
        warning_count=int(data.get("warning_count", 0) or 0),
        info_count=int(data.get("info_count", 0) or 0),
        pages=pages,
        issues=issues,
        audit_date=data.get("audit_date"),
        extras=dict(data.get("extras", {}) or {}),
    )


def load_fixture(path: str | Path, url: str | None = None) -> AuditSnapshot:
    fixture = Path(path)
    if not fixture.exists():
        raise AuditFixtureError(f"audit fixture not found: {fixture}")
    try:
        data = json.loads(fixture.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditFixtureError(f"audit fixture is not valid JSON: {fixture}: {exc}") from exc
    if not isinstance(data, dict):
        raise AuditFixtureError(f"audit fixture must be a JSON object: {fixture}")
    if "pages" not in data:
        raise AuditFixtureError(f"audit fixture has no 'pages': {fixture}")
    return snapshot_from_value(data, url=url)


def run_audit(
    url: str,
    max_pages: int | None = None,
    fixture_path: str | Path | None = None,
) -> AuditSnapshot:
    """Audit ``url`` through the vendored engine, or load a fixture.

    Fixture injection never touches the network (I-15). A missing vendored
    checkout raises a clear ImportError only on the network path (R-2).
    """

    chosen = fixture_path if fixture_path is not None else DEFAULT_FIXTURE_PATH
    if chosen is not None:
        return load_fixture(chosen, url=url)

    if not SEOEXTRACT_AVAILABLE or _SEOExtract is None:
        raise ImportError(
            f"seoextract is not importable from {config.SEOEXTRACT_DIR} at commit "
            f"{config.SEOEXTRACT_COMMIT}. Vendor the fork (see "
            "third_party/PROVENANCE.md) or run with fixture_path=."
        ) from SEOEXTRACT_IMPORT_ERROR

    _install_politeness()
    result = _SEOExtract.audit(url, max_pages=max_pages or config.MAX_OWN_PAGES)
    return snapshot_from_value(result, url=url)


__all__ = [
    "DEFAULT_FIXTURE_PATH",
    "REQUIRED_MODEL_NAMES",
    "SEOEXTRACT_AVAILABLE",
    "AuditFixtureError",
    "_install_politeness",
    "load_fixture",
    "probe_capabilities",
    "run_audit",
    "snapshot_from_value",
]
