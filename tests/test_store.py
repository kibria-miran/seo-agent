"""SQLite state, TTL cache and code-computed diffs (D-8, D-9, section 9)."""

from __future__ import annotations

import sqlite3

import pytest
from conftest import (
    make_audit,
    make_backlog_item,
    make_competitor_page,
    make_gap,
    make_issue,
    make_keyword,
    make_page,
    make_serp_result,
)

from src import config
from src.models import GapType, Severity
from src.store import Store, StoreError, cache_key, diff_snapshots

pytestmark = pytest.mark.fast


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "seo.db")
    try:
        yield value
    finally:
        value.close()


# ---------------------------------------------------------------------------
# Schema and pragmas
# ---------------------------------------------------------------------------


def test_schema_has_every_table_from_the_spec(store):
    names = set(store.table_names())
    assert {
        "runs",
        "audit_pages",
        "audit_issues",
        "keywords",
        "serp",
        "competitor_pages",
        "gaps",
        "backlog",
        "cache",
    }.issubset(names)


def test_pragmas_are_set(store):
    assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert store.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_memory_database_is_supported():
    with Store(":memory:") as memory:
        assert "runs" in memory.table_names()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_start_and_finish_run_roundtrip(store, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    store.start_run("run-a", url="https://example.co.uk")
    assert store.get_run("run-a")["status"] == "running"
    store.finish_run(
        "run-a",
        status="ok",
        site_score=87.5,
        grade="B",
        llm_calls=3,
        tokens_in=1234,
        tokens_out=567,
    )
    run = store.get_run("run-a")
    assert run["status"] == "ok"
    assert run["site_score"] == 87.5
    assert run["grade"] == "B"
    assert run["llm_calls"] == 3
    assert run["tokens_in"] == 1234
    assert run["finished_at"] == "2026-11-16T09:00:00+00:00"


def test_rerunning_the_same_run_id_is_idempotent(store):
    store.start_run("run-a", url="https://example.co.uk")
    store.save_audit("run-a", make_audit(pages=[make_page()]))
    store.start_run("run-a", url="https://example.co.uk")
    snapshot = store.load_audit("run-a")
    assert snapshot.pages == []


def test_mark_running_runs_as_aborted(store):
    store.start_run("old", url="https://example.co.uk")
    store.start_run("current", url="https://example.co.uk")
    assert store.mark_running_as_aborted(except_run_id="current") == 1
    assert store.get_run("old")["status"] == "aborted"
    assert store.get_run("current")["status"] == "running"


def test_latest_run_orders_by_started_at_then_run_id(store, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    store.start_run("run-b", url="https://example.co.uk")
    inject_clock("2026-11-16T10:00:00+00:00")
    store.start_run("run-a", url="https://example.co.uk")
    assert store.latest_run()["run_id"] == "run-a"
    assert store.latest_run(exclude="run-a")["run_id"] == "run-b"


# ---------------------------------------------------------------------------
# Audit snapshot
# ---------------------------------------------------------------------------


def test_audit_roundtrip_preserves_pages_and_issues(store):
    issue = make_issue(
        severity=Severity.CRITICAL,
        page_url="https://clearpath-mortgage.co.uk/",
    )
    page = make_page(
        issues=[issue],
        h_tags={"h1": ["Free mortgage advice"], "h2": ["Fees"]},
        schema_types=["FinancialService", "FAQPage"],
    )
    other = make_page(url="https://clearpath-mortgage.co.uk/remortgage", title="Remortgage")
    audit = make_audit(pages=[page, other], issues=[issue])

    store.start_run("run-a", url="https://clearpath-mortgage.co.uk")
    store.finish_run("run-a", status="ok", site_score=audit.site_score, grade=audit.grade)
    store.save_audit("run-a", audit)

    loaded = store.load_audit("run-a")
    assert loaded.url == "https://clearpath-mortgage.co.uk"
    assert loaded.site_score == audit.site_score
    assert loaded.grade == audit.grade
    assert len(loaded.pages) == 2
    assert [p.url for p in loaded.pages] == sorted([page.url, other.url])

    loaded_page = loaded.page(page.url)
    assert loaded_page.title == page.title
    assert loaded_page.meta_description == page.meta_description
    assert loaded_page.h_tags["h2"] == ["Fees"]
    assert loaded_page.schema_types == ["FinancialService", "FAQPage"]
    assert loaded_page.h1_tags == ["Free mortgage advice"]
    assert len(loaded_page.issues) == 1
    assert loaded_page.issues[0].severity == Severity.CRITICAL
    assert loaded.issues[0].issue_type == issue.issue_type


def test_resaving_an_audit_does_not_duplicate_rows(store):
    store.start_run("run-a", url="https://example.co.uk")
    store.save_audit("run-a", make_audit())
    store.save_audit("run-a", make_audit())
    assert store.conn.execute("SELECT COUNT(*) FROM audit_pages").fetchone()[0] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM audit_issues").fetchone()[0] == 0


def test_saving_an_audit_for_an_unknown_run_fails_loudly(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.save_audit("missing", make_audit())


def test_unknown_run_raises_store_error(store):
    with pytest.raises(StoreError, match="unknown run_id"):
        store.load_audit("nope")


# ---------------------------------------------------------------------------
# Demand tables
# ---------------------------------------------------------------------------


def test_keywords_roundtrip_and_order(store):
    store.start_run("run-a", url="https://example.co.uk")
    keywords = [
        make_keyword(keyword="zebra", source="serp"),
        make_keyword(keyword="alpha", source="suggest"),
        make_keyword(keyword="alpha", source="gsc"),
    ]
    store.save_keywords("run-a", keywords)
    loaded = store.load_keywords("run-a")
    assert [(k.keyword, k.source) for k in loaded] == [
        ("alpha", "gsc"),
        ("alpha", "suggest"),
        ("zebra", "serp"),
    ]
    assert loaded[0].intent.value == "informational"


def test_serp_roundtrip(store):
    store.start_run("run-a", url="https://example.co.uk")
    store.save_serp("run-a", [make_serp_result(rank=2), make_serp_result(rank=1)])
    loaded = store.load_serp("run-a")
    assert [item.rank for item in loaded] == [1, 2]
    assert loaded[0].domain == "moneysavingexpert.com"


def test_competitor_pages_roundtrip(store):
    store.start_run("run-a", url="https://example.co.uk")
    page = make_competitor_page()
    store.save_competitor_pages("run-a", [page])
    loaded = store.load_competitor_pages("run-a")
    assert loaded[0].h_tags == page.h_tags
    assert loaded[0].schema_types == ["FAQPage"]


def test_gaps_roundtrip(store):
    store.start_run("run-a", url="https://example.co.uk")
    gap = make_gap(evidence={"pages": ["/a"], "nested": {"b": 1}}, sources=["serp", "suggest"])
    store.save_gaps("run-a", [gap])
    loaded = store.load_gaps("run-a")[0]
    assert loaded.gap_type == GapType.NO_PAGE
    assert loaded.evidence == {"pages": ["/a"], "nested": {"b": 1}}
    assert loaded.sources == ["serp", "suggest"]


def test_backlog_roundtrip_and_order(store):
    store.start_run("run-a", url="https://example.co.uk")
    first = make_backlog_item(item_id="BL-0001", priority=1.0)
    second = make_backlog_item(item_id="BL-0002", priority=2.0, target="a")
    store.save_backlog("run-a", [first, second])
    loaded = store.load_backlog("run-a")
    assert [item.item_id for item in loaded] == ["BL-0002", "BL-0001"]
    assert loaded[0].evidence == {}


def test_issue_counts(store):
    store.start_run("run-a", url="https://example.co.uk")
    audit = make_audit(
        issues=[
            make_issue(severity=Severity.CRITICAL),
            make_issue(severity=Severity.WARNING, issue_type="Thin Content"),
            make_issue(severity=Severity.WARNING, issue_type="Missing Title"),
        ]
    )
    store.save_audit("run-a", audit)
    assert store.issue_counts("run-a") == {"CRITICAL": 1, "WARNING": 2}


# ---------------------------------------------------------------------------
# Cache (I-3)
# ---------------------------------------------------------------------------


def test_cache_key_is_source_pipe_query():
    assert cache_key("serp", " Free Mortgage Advice ") == "serp|free mortgage advice"


def test_cache_hit_within_ttl_and_miss_after(store, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    store.set_cache("suggest|remortgage", {"values": ["a", "b"]}, ttl_seconds=3600)

    inject_clock("2026-11-16T09:30:00+00:00")
    assert store.get_cache("suggest|remortgage") == {"values": ["a", "b"]}

    inject_clock("2026-11-16T11:00:00+00:00")
    assert store.get_cache("suggest|remortgage") is None
    assert store.cache_count() == 0


def test_cache_uses_injected_clock_not_the_calendar(store):
    # Fetched at a fixed epoch; a TTL of 86,400 is valid until the fixed clock
    # advances past it, regardless of today's date.
    store.set_cache("x|y", [1, 2], ttl_seconds=86400, fetched_at=1000.0)
    assert store.get_cache("x|y", now=1000.0) == [1, 2]
    assert store.get_cache("x|y", now=87399.0) == [1, 2]
    assert store.get_cache("x|y", now=87399.0) == [1, 2]
    assert store.get_cache("x|y", now=1000.0 + 86401) is None


def test_expired_cache_can_be_read_without_deleting(store):
    store.set_cache("x|y", [1], ttl_seconds=10, fetched_at=0.0)
    assert store.get_cache("x|y", now=20.0, delete_expired=False) is None
    assert store.cache_count() == 1


# ---------------------------------------------------------------------------
# Diffs (S12 / S15)
# ---------------------------------------------------------------------------


def test_diff_reports_exactly_one_new_and_one_closed_issue(store):
    old_issue = make_issue(issue_type="Duplicate Title")
    new_issue = make_issue(issue_type="Missing Meta Description")
    previous = make_audit(pages=[make_page(page_score=80.0)], issues=[old_issue], site_score=80.0)
    current = make_audit(pages=[make_page(page_score=90.0)], issues=[new_issue], site_score=90.0)

    store.start_run("previous", url="https://example.co.uk")
    store.save_audit("previous", previous)
    store.finish_run("previous", status="ok", site_score=80.0, grade="B")
    store.start_run("current", url="https://example.co.uk")
    store.save_audit("current", current)
    store.finish_run("current", status="ok", site_score=90.0, grade="A")

    diff = store.diff_runs("previous", "current")
    assert diff.score_delta == 10.0
    assert len(diff.new_items) == 1
    assert "Missing Meta Description" in diff.new_items[0]
    assert len(diff.closed_items) == 1
    assert "Duplicate Title" in diff.closed_items[0]


def test_first_run_has_no_closed_items(store):
    store.start_run("current", url="https://example.co.uk")
    store.save_audit("current", make_audit(issues=[make_issue()]))
    store.finish_run("current", status="ok", site_score=90.0, grade="A")
    diff = store.diff_runs(None, "current")
    assert len(diff.new_items) == 1
    assert diff.closed_items == []


def test_diff_snapshots_is_a_pure_function():
    previous = make_audit(issues=[make_issue(issue_type="A")], site_score=50.0)
    current = make_audit(issues=[make_issue(issue_type="B")], site_score=60.0)
    first = diff_snapshots(previous, current).model_dump()
    second = diff_snapshots(previous, current).model_dump()
    assert first == second
    assert first["score_delta"] == 10.0


def test_diff_includes_gap_churn(store):
    store.start_run("previous", url="https://example.co.uk")
    store.save_audit("previous", make_audit())
    store.save_gaps("previous", [make_gap(keyword="old topic")])
    store.finish_run("previous", status="ok", site_score=80.0, grade="B")

    store.start_run("current", url="https://example.co.uk")
    store.save_audit("current", make_audit())
    store.save_gaps("current", [make_gap(keyword="new topic")])
    store.finish_run("current", status="ok", site_score=80.0, grade="B")

    diff = store.diff_runs("previous", "current")
    assert diff.new_gaps == ["new topic :: NO_PAGE"]
    assert diff.closed_gaps == ["old topic :: NO_PAGE"]


# ---------------------------------------------------------------------------
# Transactions and durability
# ---------------------------------------------------------------------------


def test_transaction_rolls_back_on_error(store):
    store.start_run("run-a", url="https://example.co.uk")
    with pytest.raises(RuntimeError), store.transaction() as conn:
        conn.execute(
            "INSERT INTO cache(key, fetched_at, ttl_seconds, payload) VALUES ('x|y', 0, 1, '[]')"
        )
        raise RuntimeError("simulated crash")
    assert store.cache_count() == 0

    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO cache(key, fetched_at, ttl_seconds, payload) VALUES ('x|y', 0, 1, '[]')"
        )
    assert store.cache_count() == 1


def test_ttl_default_is_24_hours(store):
    store.set_cache("a|b", {})
    row = store.conn.execute("SELECT ttl_seconds FROM cache WHERE key='a|b'").fetchone()
    assert row["ttl_seconds"] == config.CACHE_TTL_SECONDS


def test_diff_refuses_cross_domain_baseline(store):
    previous = make_audit(issues=[make_issue(issue_type="Duplicate Title")], site_score=80.0)
    current = make_audit(issues=[make_issue(issue_type="Missing Title")], site_score=89.0)
    store.start_run("previous", url="https://clearpath-mortgage.co.uk")
    store.save_audit("previous", previous)
    store.save_gaps("previous", [make_gap(keyword="old topic")])
    store.finish_run("previous", status="ok", site_score=80.0, grade="B")
    store.start_run("current", url="https://landc-mortgage.co.uk")
    store.save_audit("current", current)
    store.save_gaps("current", [make_gap(keyword="new topic")])
    store.finish_run("current", status="ok", site_score=89.0, grade="B")

    diff = store.diff_runs("previous", "current")
    assert diff.closed_items == []
    assert diff.closed_gaps == []


def test_latest_run_scopes_to_domain(store):
    store.start_run("run-a", url="https://a.co.uk", started_at="2026-11-16T09:00:00+00:00")
    store.finish_run("run-a", status="ok", site_score=10.0, grade="F")
    store.start_run("run-b", url="https://b.co.uk", started_at="2026-11-17T09:00:00+00:00")
    store.finish_run("run-b", status="ok", site_score=20.0, grade="F")

    assert store.latest_run(exclude="run-b", domain="https://b.co.uk") is None
    assert store.latest_run(exclude="run-b", domain="https://a.co.uk")["run_id"] == "run-a"
    assert store.latest_run(exclude="run-b")["run_id"] == "run-a"
