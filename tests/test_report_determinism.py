"""Report rendering is deterministic, timestamp-free in the body, and safe.

I-20: two renders from the same DB state are byte-identical.
"""

from __future__ import annotations

import json
import re

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

from src import clock
from src.models import AuditDiff, Severity
from src.report import (
    ReportError,
    render_backlog_json,
    render_report,
    write_report,
)
from src.store import Store

pytestmark = pytest.mark.fast

SITE = "https://clearpath-mortgage.co.uk"


def sample_run(**overrides):
    data = {
        "run_id": "run-a",
        "url": SITE,
        "status": "ok",
        "site_score": 87.5,
        "grade": "B",
        "llm_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "backlog_count": 3,
    }
    data.update(overrides)
    return data


def sample_audit():
    issues = [
        make_issue(
            page_url=f"{SITE}/remortgage",
            issue_type="Duplicate Title",
            severity=Severity.WARNING,
        ),
        make_issue(
            page_url=f"{SITE}/first-time-buyer",
            issue_type="Multiple H1 Tags",
            severity=Severity.CRITICAL,
        ),
        make_issue(
            page_url=f"{SITE}/buy-to-let",
            issue_type="Thin Content",
            severity=Severity.INFO,
        ),
    ]
    pages = [
        make_page(url=f"{SITE}/", page_score=100.0),
        make_page(url=f"{SITE}/remortgage", title="Remortgage Advice", page_score=75.0),
    ]
    return make_audit(pages=pages, issues=issues, site_score=87.5, grade="B")


def sample_diff():
    return AuditDiff(
        score_delta=2.5,
        new_items=[f"{SITE}/remortgage :: Duplicate Title"],
        closed_items=[f"{SITE}/first-time-buyer :: Missing Meta Description"],
        new_gaps=["bad credit mortgage :: NO_PAGE"],
        closed_gaps=["old topic :: NO_PAGE"],
    )


def sample_backlog(count=3):
    return [
        make_backlog_item(
            item_id=f"BL-{index:04d}",
            target=f"/topic-{index}",
            priority=float(count - index),
            title=f"Create page {index}",
            evidence={"serp": [f"https://example.com/{index}"]},
        )
        for index in range(1, count + 1)
    ]


def render(**overrides):
    kwargs = {
        "diff": sample_diff(),
        "backlog": sample_backlog(),
        "gaps": [
            make_gap(
                keyword="bad credit mortgage",
                gap_type="NO_PAGE",
                sources=["keywords", "serp"],
                target="/bad-credit-mortgage",
            )
        ],
        "keywords": [make_keyword(keyword="bad credit mortgage")],
        "serp": [make_serp_result()],
        "competitor_pages": [
            make_competitor_page(domain="habito.com"),
            make_competitor_page(domain="trussle.com", schema_types=["FAQPage"]),
        ],
        "drafts": ["remortgage.md", "bad-credit-mortgage.md"],
        "budgets": {"steps": 5, "fetches": 12},
        "previous_run_id": "run-previous",
        "generated_at": "2026-11-16T09:00:00+00:00",
    }
    kwargs.update(overrides)
    run = kwargs.pop("run", sample_run())
    return render_report(run, kwargs.pop("audit", sample_audit()), **kwargs)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_renders_are_byte_identical():
    assert render() == render()


def test_two_renders_from_the_same_database_state_are_byte_identical(tmp_path, inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    store = Store(tmp_path / "seo.db")
    try:
        audit = sample_audit()
        backlog = sample_backlog()
        store.start_run("run-a", url=SITE)
        store.finish_run("run-a", status="ok", site_score=87.5, grade="B")
        store.save_audit("run-a", audit)
        store.save_backlog("run-a", backlog)
        store.save_keywords("run-a", [make_keyword()])

        def build():
            return render_report(
                store.get_run("run-a") | {"backlog_count": len(backlog)},
                store.load_audit("run-a"),
                diff=sample_diff(),
                backlog=store.load_backlog("run-a"),
                keywords=store.load_keywords("run-a"),
                budgets={"steps": 5, "fetches": 12},
                previous_run_id="run-previous",
            )

        first = build()
        second = build()
        assert first == second
    finally:
        store.close()


def test_body_is_timestamp_free_but_header_uses_the_clock(inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00")
    first = render(generated_at=None)
    inject_clock("2026-11-17T10:30:00+00:00")
    second = render(generated_at=None)

    assert "2026-11-16T09:00:00+00:00" in first
    assert "2026-11-17T10:30:00+00:00" in second
    assert first.split("## Scorecard", 1)[1] == second.split("## Scorecard", 1)[1]
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", first.split("## Scorecard", 1)[1])


def test_clock_is_the_only_source_of_the_header_timestamp(inject_clock):
    inject_clock("2026-01-02T03:04:05+00:00")
    text = render(generated_at=None)
    assert "2026-01-02T03:04:05+00:00" in text
    assert clock.now().isoformat(timespec="seconds") == "2026-01-02T03:04:05+00:00"


# ---------------------------------------------------------------------------
# Content and sections
# ---------------------------------------------------------------------------


def test_sections_are_present_in_a_stable_order():
    text = render()
    headings = [
        "## Scorecard",
        "## New issues since previous run",
        "## Issues closed since previous run",
        "## New gaps since previous run",
        "## Gaps closed since previous run",
        "## Open gaps",
        "## Top backlog",
        "## This week / next week / later",
        "## Competitor coverage",
        "## SERP evidence",
        "## Drafts",
        "## Run budgets",
    ]
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_scorecard_numbers_come_from_the_models():
    text = render()
    assert "Site score: **87.5** (B)" in text
    assert "Delta vs previous run: +2.5" in text
    assert "Issues: 3 total · 1 critical · 1 warning · 1 info" in text
    assert "Keywords mined: 1" in text
    assert "Gaps open: 1" in text
    assert "Backlog items: 3" in text


def test_first_run_says_so_instead_of_showing_a_fake_delta():
    text = render(previous_run_id=None)
    assert "Delta vs previous run: n/a (first run)" in text


def test_new_and_closed_items_are_listed():
    text = render()
    assert f"{SITE}/remortgage :: Duplicate Title" in text
    assert f"{SITE}/first-time-buyer :: Missing Meta Description" in text
    assert "bad credit mortgage :: NO_PAGE" in text
    assert "old topic :: NO_PAGE" in text


def test_open_gaps_show_type_target_and_sources():
    text = render()
    assert "`NO_PAGE` **bad credit mortgage**" in text
    assert "`/bad-credit-mortgage`" in text
    assert "sources: keywords, serp" in text


def test_backlog_is_capped_at_ten_and_keeps_priority_order():
    items = sample_backlog(count=12)
    text = render(backlog=items)
    assert "Showing 10 of 12 items" in text
    backlog_section = text.split("## Top backlog", 1)[1].split(
        "## This week / next week / later", 1
    )[0]
    assert "BL-0001" in backlog_section
    assert "BL-0010" in backlog_section
    assert "BL-0011" not in backlog_section
    assert text.index("BL-0001") < text.index("BL-0002")


def test_week_plan_packs_by_effort_budget_and_keeps_priority_order():
    items = [
        make_backlog_item(item_id="BL-0001", title="Schema umbrella", effort=8, priority=0.9),
        make_backlog_item(item_id="BL-0002", title="Create bad credit page", effort=3, priority=0.8),
        make_backlog_item(item_id="BL-0003", title="Create borrow page", effort=3, priority=0.7),
        make_backlog_item(item_id="BL-0004", title="Create calculator page", effort=3, priority=0.6),
        make_backlog_item(item_id="BL-0005", title="Fix meta", effort=1, priority=0.5),
    ]
    text = render(backlog=items)
    assert "## This week / next week / later" in text
    week1 = text.split("**This week**", 1)[1].split("**Next week**", 1)[0]
    week2 = text.split("**Next week**", 1)[1].split("**Week after**", 1)[0]
    assert "BL-0001" in week1
    assert "BL-0002" not in week1
    assert "BL-0002" in week2


def test_week_plan_handles_empty_backlog():
    text = render(backlog=[])
    assert "## This week / next week / later" in text
    assert "_No backlog items produced._" in text


def test_empty_sections_are_explicit_not_missing():
    text = render(
        backlog=[],
        gaps=[],
        keywords=[],
        serp=[],
        competitor_pages=[],
        drafts=[],
    )
    assert "_No backlog items produced._" in text
    assert "_None._" in text
    assert "_No competitor pages parsed._" in text
    assert "_No SERP results this run._" in text
    assert "_No drafts written this run._" in text


def test_competitor_notes_group_by_domain_deterministically():
    text = render()
    assert "**habito.com**: 1 page(s)" in text
    assert "**trussle.com**: 1 page(s)" in text
    assert "schema: FAQPage" in text
    assert text.index("habito.com") < text.index("trussle.com")


def test_drafts_are_sorted():
    text = render(drafts=["zeta.md", "alpha.md"])
    assert text.index("alpha.md") < text.index("zeta.md")


def test_partial_status_is_visible():
    text = render(run=sample_run(status="partial"))
    assert "status partial" in text
    assert "Status: `partial`" in text


def test_budget_section_uses_caps():
    text = render(budgets={"steps": 5, "fetches": 12, "llm_calls": 2, "tokens_in": 100, "tokens_out": 20})
    assert "Steps: 5 / 12" in text
    assert "LLM calls: 2 / 20" in text
    assert "Tokens: 100 in / 20 out" in text
    assert "Fetches: 12 / 120" in text


# ---------------------------------------------------------------------------
# Backlog JSON and writer
# ---------------------------------------------------------------------------


def test_backlog_json_is_stable_and_parseable():
    items = sample_backlog()
    first = render_backlog_json(items)
    second = render_backlog_json(items)
    assert first == second
    parsed = json.loads(first)
    assert [item["item_id"] for item in parsed] == ["BL-0001", "BL-0002", "BL-0003"]
    assert first.endswith("\n")


def test_write_report_stays_under_out_and_writes_expected_files(tmp_path):
    from conftest import assert_write_paths_under

    out_root = tmp_path / "out"
    with assert_write_paths_under(tmp_path, allowed=("out/", "logs/")) as written:
        paths = write_report(
            "run-a",
            "# report\n",
            sample_backlog(),
            drafts={"remortgage.md": "# draft\n"},
            out_root=out_root,
        )

    assert paths["report"].read_text(encoding="utf-8") == "# report\n"
    assert json.loads(paths["backlog"].read_text(encoding="utf-8"))[0]["item_id"] == "BL-0001"
    assert paths["draft:remortgage.md"].read_text(encoding="utf-8") == "# draft\n"
    assert all("/out/run-a/" in path for path in written)


def test_write_report_rejects_unsafe_run_ids(tmp_path):
    for run_id in ("../escape", "a/b", "", ".", ".."):
        with pytest.raises(ReportError):
            write_report(run_id, "x", [], out_root=tmp_path / "out")


def test_write_report_rejects_unsafe_draft_names(tmp_path):
    for name in ("../x.md", "a/b.md", "x.txt", "x"):
        with pytest.raises(ReportError):
            write_report("run-a", "x", [], drafts={name: "y\n"}, out_root=tmp_path / "out")


def test_write_report_is_idempotent(tmp_path):
    out_root = tmp_path / "out"
    first = write_report("run-a", "one\n", sample_backlog(), out_root=out_root)
    second = write_report("run-a", "one\n", sample_backlog(), out_root=out_root)
    assert first["report"].read_text(encoding="utf-8") == "one\n"
    assert second["report"].read_text(encoding="utf-8") == "one\n"
