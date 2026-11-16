"""Audit adapter: real capability probe, fixture injection, conversion.

The adapter is the only source module allowed to import seoextract. These tests
pin the real 0.3.0 names and prove that the fast tier never touches the
network (I-15).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests

from src import audit_adapter, config
from src.audit_adapter import (
    AuditFixtureError,
    load_fixture,
    probe_capabilities,
    run_audit,
    snapshot_from_value,
)
from src.models import Severity

pytestmark = pytest.mark.fast

FIXTURE = config.FIXTURES_DIR / "own_site_audit.json"
SITE = "https://clearpath-mortgage.co.uk"


# ---------------------------------------------------------------------------
# Capability probe (R-1 / R-2)
# ---------------------------------------------------------------------------


def test_vendored_seoextract_is_importable_and_has_real_names():
    assert audit_adapter.SEOEXTRACT_AVAILABLE, audit_adapter.SEOEXTRACT_IMPORT_ERROR
    from seoextract import SEOExtract, models

    probe_capabilities(models, SEOExtract)
    for name in ("AuditResult", "PageData", "SEOIssue"):
        assert hasattr(models, name)
    assert callable(SEOExtract.audit)


def test_probe_names_a_missing_model_symbol():
    partial = SimpleNamespace(AuditResult=object, PageData=object)

    class Core:
        class SEOExtract:
            @staticmethod
            def audit(url, max_pages=20):  # pragma: no cover - never called
                return None

    with pytest.raises(ImportError, match="SEOIssue"):
        probe_capabilities(partial, Core)


def test_probe_names_a_missing_audit_method():
    complete = SimpleNamespace(AuditResult=object, PageData=object, SEOIssue=object)

    class Core:
        class SEOExtract:
            pass

    with pytest.raises(ImportError, match="SEOExtract.audit"):
        probe_capabilities(complete, Core)


def test_probe_accepts_a_complete_fake():
    complete = SimpleNamespace(AuditResult=object, PageData=object, SEOIssue=object)

    class Core:
        class SEOExtract:
            @staticmethod
            def audit(url, max_pages=20):
                return None

    probe_capabilities(complete, Core)  # must not raise


def test_probe_error_mentions_the_pinned_commit():
    with pytest.raises(ImportError) as excinfo:
        probe_capabilities(SimpleNamespace(), None)
    assert config.SEOEXTRACT_COMMIT in str(excinfo.value)


# ---------------------------------------------------------------------------
# Fixture injection (I-15)
# ---------------------------------------------------------------------------


def test_fixture_path_converts_to_our_snapshot():
    snapshot = run_audit(SITE, fixture_path=FIXTURE)
    assert snapshot.url == SITE
    assert snapshot.pages_crawled == 6
    assert snapshot.total_issues == 7
    assert snapshot.site_score == 87.5
    assert snapshot.grade == "B"
    assert snapshot.critical_count == 1
    assert snapshot.warning_count == 5
    assert snapshot.info_count == 1
    assert len(snapshot.pages) == 6
    assert len(snapshot.issues) == 7


def test_fixture_field_mapping_uses_real_seoextract_names():
    snapshot = load_fixture(FIXTURE)
    page = snapshot.page(f"{SITE}/first-time-buyer")
    assert page is not None
    assert page.title == "First Time Buyer Mortgage Guide"
    assert page.meta_description is None
    assert page.meta_desc is None  # read-only alias
    assert page.h1_count == 2
    assert page.h1 == "First-time buyer mortgage guide"
    assert page.word_count == 1180
    assert page.schema_types == ["FinancialService", "FAQPage", "BreadcrumbList"]

    issue = next(i for i in snapshot.issues if i.issue_type == "Multiple H1 Tags")
    assert issue.severity == Severity.CRITICAL
    assert issue.page_url.endswith("/first-time-buyer")


def test_inject_fixture_sets_the_adapter_default(inject_fixture):
    path = inject_fixture("own_site_audit.json")
    assert path == FIXTURE
    snapshot = run_audit(SITE)  # no fixture_path argument
    assert snapshot.pages_crawled == 6


def test_fixture_never_touches_the_network(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network was touched during a fixture audit")

    monkeypatch.setattr(requests.sessions.Session, "request", explode)
    snapshot = run_audit(SITE, fixture_path=FIXTURE)
    assert snapshot.pages_crawled == 6


def test_missing_fixture_raises_a_clear_error(tmp_path):
    with pytest.raises(AuditFixtureError, match="not found"):
        run_audit(SITE, fixture_path=tmp_path / "missing.json")


def test_invalid_json_fixture_raises_a_clear_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(AuditFixtureError, match="not valid JSON"):
        load_fixture(bad)


def test_fixture_without_pages_raises_a_clear_error(tmp_path):
    bad = tmp_path / "no-pages.json"
    bad.write_text(json.dumps({"url": SITE}), encoding="utf-8")
    with pytest.raises(AuditFixtureError, match="no 'pages'"):
        load_fixture(bad)


def test_non_object_fixture_raises_a_clear_error(tmp_path):
    bad = tmp_path / "list.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(AuditFixtureError, match="JSON object"):
        load_fixture(bad)


# ---------------------------------------------------------------------------
# Conversion of our own shape and the real seoextract models
# ---------------------------------------------------------------------------


def test_snapshot_from_value_accepts_our_fixture_shape(tmp_path):
    data = {
        "domain": "https://example.co.uk",
        "site_score": 70.0,
        "grade": "C",
        "pages": [
            {
                "url": "https://example.co.uk/",
                "status_code": 200,
                "meta_desc": "Old spelling from the v1.1 draft",
                "h1_tags": ["Hello"],
                "h1_count": 0,
                "word_count": 120,
            }
        ],
        "issues": [
            {
                "page_url": "https://example.co.uk/",
                "issue_type": "Missing Title",
                "severity": "critical",
                "current_value": "",
                "suggestion": "Add a title",
            }
        ],
    }
    snapshot = snapshot_from_value(data)
    assert snapshot.url == "https://example.co.uk"
    assert snapshot.pages[0].meta_description.startswith("Old spelling")
    assert snapshot.pages[0].h1_count == 1  # synced from h1_tags
    assert snapshot.issues[0].severity == Severity.CRITICAL


def test_snapshot_from_real_seoextract_models():
    from seoextract.models import AuditResult, IssueType
    from seoextract.models import PageData as UpstreamPage
    from seoextract.models import SEOIssue as UpstreamIssue
    from seoextract.models import Severity as UpstreamSeverity

    issue = UpstreamIssue(
        page_url="https://example.co.uk/remortgage",
        issue_type=IssueType.DUPLICATE_TITLE,
        severity=UpstreamSeverity.WARNING,
        current_value="Remortgage Advice",
        suggestion="Make it unique",
    )
    page = UpstreamPage(
        url="https://example.co.uk/remortgage",
        response_time_ms=123.0,
        status_code=200,
        title="Remortgage Advice",
        meta_description="Compare options.",
        h1_tags=["Remortgage advice"],
        h1_count=1,
        word_count=600,
        page_score=92.0,
        schema_found=True,
        issues=[issue],
    )
    result = AuditResult(
        url="https://example.co.uk",
        audit_date="2026-11-16 09:00",
        pages_crawled=1,
        site_score=92.0,
        grade="A",
        total_issues=1,
        critical_count=0,
        warning_count=1,
        info_count=0,
        pages=[page],
        issues=[issue],
    )

    snapshot = snapshot_from_value(result)
    assert snapshot.url == "https://example.co.uk"
    assert snapshot.audit_date == "2026-11-16 09:00"
    assert snapshot.pages[0].meta_description == "Compare options."
    assert snapshot.pages[0].schema_types == ["unknown"]  # schema_found fallback
    assert snapshot.issues[0].issue_type == "Duplicate Title"  # enum -> label
    assert snapshot.issues[0].severity == Severity.WARNING


def test_page_issues_are_aggregated_when_top_level_issues_are_absent():
    page = {
        "url": "https://example.co.uk/",
        "issues": [
            {
                "page_url": "https://example.co.uk/",
                "issue_type": "Thin Content",
                "severity": "INFO",
                "suggestion": "Expand",
            }
        ],
    }
    snapshot = snapshot_from_value({"pages": [page], "issues": []})
    assert len(snapshot.issues) == 1
    assert snapshot.total_issues == 1


# ---------------------------------------------------------------------------
# Network path guard and max_pages forwarding
# ---------------------------------------------------------------------------


def test_network_path_forwards_max_pages(monkeypatch):
    captured: dict[str, object] = {}

    class FakeExtract:
        @staticmethod
        def audit(url, max_pages=20):
            captured["url"] = url
            captured["max_pages"] = max_pages
            return {"url": url, "pages": [], "issues": [], "site_score": 90.0, "grade": "A"}

    monkeypatch.setattr(audit_adapter, "_SEOExtract", FakeExtract)
    monkeypatch.setattr(audit_adapter, "SEOEXTRACT_AVAILABLE", True)
    snapshot = run_audit(SITE, max_pages=7)
    assert captured == {"url": SITE, "max_pages": 7}
    assert snapshot.grade == "A"


def test_missing_vendored_checkout_raises_a_clear_import_error(monkeypatch):
    monkeypatch.setattr(audit_adapter, "_SEOExtract", None)
    monkeypatch.setattr(audit_adapter, "SEOEXTRACT_AVAILABLE", False)
    with pytest.raises(ImportError, match="not importable"):
        run_audit(SITE)
