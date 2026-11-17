"""End-to-end deterministic pipeline: fixture in, report + backlog out.

Covers S1 (golden fixture, byte-identical rerun), S2 (zero issues), S15
(two-run real diff) and the aborted-run durability rule.
"""

from __future__ import annotations

import json

import pytest
import requests
from typer.testing import CliRunner

from src import config
from src.audit_adapter import AuditFixtureError
from src.cli import app
from src.models import GapType
from src.pipeline import (
    build_clusters,
    build_keywords,
    default_run_id,
    load_profile,
    money_keywords_for,
    run_deterministic,
)
from src.store import Store

pytestmark = pytest.mark.fast

FIXTURE = config.FIXTURES_DIR / "own_site_audit.json"


@pytest.fixture
def profile():
    return load_profile(config.PROFILES_DIR / "site.json")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_variant(path, *, score=90.0):
    data = read_json(FIXTURE)
    data["site_score"] = score
    data["grade"] = config.grade_for(score)
    data["issues"] = [
        issue
        for issue in data["issues"]
        if not (
            issue["page_url"].endswith("/remortgage")
            and issue["issue_type"] == "Duplicate Title"
        )
    ]
    data["issues"].append(
        {
            "page_url": "https://clearpath-mortgage.co.uk/free-mortgage-advice",
            "issue_type": "Missing Title",
            "severity": "CRITICAL",
            "current_value": "",
            "suggestion": "Add a unique title.",
        }
    )
    data["total_issues"] = len(data["issues"])
    data["critical_count"] = sum(i["severity"] == "CRITICAL" for i in data["issues"])
    data["warning_count"] = sum(i["severity"] == "WARNING" for i in data["issues"])
    data["info_count"] = sum(i["severity"] == "INFO" for i in data["issues"])
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Profile / keyword helpers
# ---------------------------------------------------------------------------


def test_load_profile_from_the_repo_file(profile):
    assert profile.domain == "https://clearpath-mortgage.co.uk"
    assert len(profile.target_keywords) == 10


def test_load_profile_accepts_a_bare_name(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path)
    (tmp_path / "site.json").write_text(
        json.dumps(
            {
                "domain": "https://example.co.uk",
                "money_pages": ["/"],
                "target_keywords": ["free mortgage advice"],
                "competitors": ["habito.com"],
                "cities": ["London"],
                "fca_firm_ref": "123456",
            }
        ),
        encoding="utf-8",
    )
    assert load_profile("site.json").domain == "https://example.co.uk"


def test_load_profile_rejects_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profile(tmp_path / "nope.json")


def test_build_keywords_normalises_and_classifies(profile):
    keywords = build_keywords(profile)
    assert len(keywords) == 10
    assert all(keyword.source == "profile" for keyword in keywords)
    manchester = next(k for k in keywords if "manchester" in k.keyword)
    assert manchester.intent.value == "local"
    assert manchester.city == "Manchester"
    near_me = next(k for k in keywords if "near me" in k.keyword)
    assert near_me.intent.value == "local"
    calculator = next(k for k in keywords if "calculator" in k.keyword)
    assert calculator.intent.value == "informational"


def test_build_clusters_assigns_ids_back_to_keywords(profile):
    keywords = build_keywords(profile)
    clusters = build_clusters(keywords)
    assert clusters
    assert all(keyword.cluster_id for keyword in keywords)
    members = {member for item in clusters for member in item.keywords}
    assert members == {keyword.keyword for keyword in keywords}


def test_money_keywords_come_from_money_page_slugs(profile):
    # The homepage is skipped and slugs are turned into search phrasing;
    # otherwise "every keyword is a money keyword" and CRITICAL means nothing.
    assert money_keywords_for(profile) == ["free mortgage advice", "remortgage"]


def test_money_keywords_ignore_the_homepage_and_duplicates():
    from conftest import make_profile

    profile = make_profile(
        money_pages=["/", "/Remortgage", "/remortgage/", "/buy-to-let-mortgage"]
    )
    assert money_keywords_for(profile) == ["buy to let mortgage", "remortgage"]


def test_default_run_id_uses_the_injected_clock(inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    assert default_run_id() == "run-20261116T090000Z"


# ---------------------------------------------------------------------------
# S1: golden fixture run
# ---------------------------------------------------------------------------


def test_S1_golden_fixture_run_writes_report_and_backlog(tmp_path, profile, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    db = tmp_path / "seo.db"
    out = tmp_path / "out"

    report = run_deterministic(
        profile,
        fixture_path=FIXTURE,
        run_id="run-golden",
        db_path=db,
        out_root=out,
    )

    assert report.status == "ok"
    assert report.site_score == 87.5
    assert report.grade == "B"
    assert report.backlog
    assert {item.gap_type for item in report.backlog} <= {
        GapType.NO_PAGE.value,
        GapType.LOCAL_MISSING.value,
        GapType.COMP_COVERS.value,
        GapType.WEAK_PAGE.value,
        GapType.SCHEMA_MISSING.value,
    }
    assert GapType.NO_PAGE.value in {item.gap_type for item in report.backlog}
    assert GapType.LOCAL_MISSING.value in {item.gap_type for item in report.backlog}

    report_path = out / "run-golden" / "report.md"
    backlog_path = out / "run-golden" / "backlog.json"
    assert report_path.exists()
    assert backlog_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "## Scorecard" in text
    assert "Site score: **87.5** (B)" in text
    assert "## Top backlog" in text
    assert "bad credit mortgage" in text
    assert read_json(backlog_path)[0]["item_id"] == "BL-0001"

    with Store(db) as store:
        run = store.get_run("run-golden")
        assert run["status"] == "ok"
        assert run["llm_calls"] == 0
        assert len(store.load_audit("run-golden").pages) == 6
        assert store.load_keywords("run-golden")
        assert store.load_gaps("run-golden")
        assert store.load_backlog("run-golden") == report.backlog


def test_S1_rerunning_the_same_run_id_is_byte_identical(tmp_path, profile, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    db = tmp_path / "seo.db"
    out = tmp_path / "out"
    kwargs = {"fixture_path": FIXTURE, "run_id": "run-golden", "db_path": db, "out_root": out}

    run_deterministic(profile, **kwargs)
    first_report = (out / "run-golden" / "report.md").read_bytes()
    first_backlog = (out / "run-golden" / "backlog.json").read_bytes()

    run_deterministic(profile, **kwargs)
    assert (out / "run-golden" / "report.md").read_bytes() == first_report
    assert (out / "run-golden" / "backlog.json").read_bytes() == first_backlog


def test_fixture_run_never_touches_the_network(tmp_path, profile, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network touched in fixture mode")

    monkeypatch.setattr(requests.sessions.Session, "request", explode)
    report = run_deterministic(
        profile,
        fixture_path=FIXTURE,
        run_id="run-offline",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
    )
    assert report.status == "ok"


# ---------------------------------------------------------------------------
# S2: zero issues still produces useful gaps
# ---------------------------------------------------------------------------


def test_S2_zero_issue_site_still_produces_gap_items(tmp_path, profile):
    data = read_json(FIXTURE)
    data["issues"] = []
    data["total_issues"] = 0
    data["critical_count"] = 0
    data["warning_count"] = 0
    data["info_count"] = 0
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps(data), encoding="utf-8")

    report = run_deterministic(
        profile,
        fixture_path=clean,
        run_id="run-clean",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
    )
    assert report.status == "ok"
    assert report.backlog
    assert all(item.gap_type in {GapType.NO_PAGE.value, GapType.LOCAL_MISSING.value} for item in report.backlog)


# ---------------------------------------------------------------------------
# S15: two real runs, one issue closed and one introduced
# ---------------------------------------------------------------------------


def test_S15_two_run_diff_reports_one_closed_and_one_new(tmp_path, profile, inject_clock):
    variant = make_variant(tmp_path / "variant.json", score=90.0)
    db = tmp_path / "seo.db"
    out = tmp_path / "out"

    inject_clock("2026-11-16T09:00:00+00:00")
    run_deterministic(
        profile,
        fixture_path=FIXTURE,
        run_id="run-a",
        db_path=db,
        out_root=out,
    )

    inject_clock("2026-11-17T09:00:00+00:00")
    report = run_deterministic(
        profile,
        fixture_path=variant,
        run_id="run-b",
        db_path=db,
        out_root=out,
    )

    assert len(report.diff.new_items) == 1
    assert len(report.diff.closed_items) == 1
    assert "Missing Title" in report.diff.new_items[0]
    assert "Duplicate Title" in report.diff.closed_items[0]
    assert report.diff.score_delta == 2.5

    text = (out / "run-b" / "report.md").read_text(encoding="utf-8")
    assert "Delta vs previous run: +2.5" in text
    assert "Issues closed since previous run" in text
    assert "Missing Title" in text
    assert "Duplicate Title" in text


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def test_stale_running_run_is_marked_aborted(tmp_path, profile):
    db = tmp_path / "seo.db"
    with Store(db) as store:
        store.start_run("stale", url="https://clearpath-mortgage.co.uk")

    run_deterministic(
        profile,
        fixture_path=FIXTURE,
        run_id="run-new",
        db_path=db,
        out_root=tmp_path / "out",
    )
    with Store(db) as store:
        assert store.get_run("stale")["status"] == "aborted"
        assert store.get_run("run-new")["status"] == "ok"


def test_failed_run_is_marked_aborted(tmp_path, profile):
    db = tmp_path / "seo.db"
    with pytest.raises(AuditFixtureError):
        run_deterministic(
            profile,
            fixture_path=tmp_path / "missing.json",
            run_id="run-bad",
            db_path=db,
            out_root=tmp_path / "out",
        )
    with Store(db) as store:
        assert store.get_run("run-bad")["status"] == "aborted"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_no_llm_fixture_run(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--site",
            str(config.PROFILES_DIR / "site.json"),
            "--no-llm",
            "--fixture",
            str(FIXTURE),
            "--run-id",
            "cli-run",
            "--db",
            str(tmp_path / "seo.db"),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "complete" in result.output.lower()
    assert (tmp_path / "out" / "cli-run" / "report.md").exists()


def test_cli_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "seo-agent" in result.output
    assert config.SEOEXTRACT_COMMIT[:8] in result.output


def test_cross_domain_run_produces_no_diff_against_other_sites_baseline(tmp_path, profile, inject_clock):
    other_data = read_json(config.PROFILES_DIR / "site.json")
    other_data["domain"] = "https://landc-mortgage.co.uk"
    other_path = tmp_path / "landc.json"
    other_path.write_text(json.dumps(other_data), encoding="utf-8")
    other = load_profile(other_path)
    variant = make_variant(tmp_path / "variant.json", score=90.0)
    db = tmp_path / "seo.db"
    out = tmp_path / "out"

    inject_clock("2026-11-16T09:00:00+00:00")
    run_deterministic(profile, fixture_path=FIXTURE, run_id="run-a", db_path=db, out_root=out)

    inject_clock("2026-11-17T09:00:00+00:00")
    report = run_deterministic(other, fixture_path=variant, run_id="run-b", db_path=db, out_root=out)

    assert report.diff.closed_items == []
    assert report.diff.closed_gaps == []
    text = (out / "run-b" / "report.md").read_text(encoding="utf-8")
    assert "No comparable previous run for landc-mortgage.co.uk." in text


def test_pipeline_survives_fetch_budget_refusal(tmp_path, profile, inject_clock, monkeypatch):
    """Drive the crawl past the fetch cap with a fake crawler.

    Robots (2 fetches) plus the homepage spend a MAX_FETCHES=3 budget, so the
    second page is refused with a synthetic 429. The report must still
    generate, the trace must record the budget event, and the audit snapshot
    must carry the synthetic-429 page in a way gap analysis tolerates.
    """
    from seoextract import crawler

    from src import audit_adapter

    inject_clock("2026-11-17T15:06:56+00:00")

    def fake_fetch(url, session):
        if url == "https://clearpath-mortgage.co.uk/":
            html = (
                "<html><head><title>Clearpath</title></head>"
                "<body><h1>Clearpath</h1>"
                "<a href='/remortgage'>remortgage</a>"
                "<a href='/free-mortgage-advice'>advice</a>"
                "</body></html>"
            )
        else:
            html = "<html></html>"
        return {
            "url": url,
            "final_url": url,
            "status_code": 200,
            "html": html,
            "response_time_ms": 1.0,
        }

    monkeypatch.setattr(crawler, "fetch_page", fake_fetch)
    monkeypatch.setattr(crawler, "_load_robots", lambda base: None)
    monkeypatch.setattr(config, "MAX_FETCHES", 3)
    monkeypatch.setattr(audit_adapter.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(audit_adapter, "_POLITENESS_INSTALLED", False)
    audit_adapter.reset_fetch_count()

    trace_path = tmp_path / "trace.jsonl"
    try:
        report = run_deterministic(
            profile,
            run_id="run-budget-refusal",
            db_path=tmp_path / "seo.db",
            out_root=tmp_path / "out",
            trace_path=trace_path,
        )

        assert report.status == "ok"
        assert audit_adapter.fetch_budget_exhausted()
        assert report.backlog

        events = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
        ]
        assert any(
            e.get("step") == "budget" and e.get("reason") == "max_fetches" for e in events
        )

        with Store(tmp_path / "seo.db") as store:
            snapshot = store.load_audit("run-budget-refusal")
        refused = [p for p in snapshot.pages if p.status_code == 429]
        assert refused
    finally:
        audit_adapter.reset_fetch_count()
