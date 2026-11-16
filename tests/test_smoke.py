"""Trivial process-gate test (D-11).

If this file does not pass, no line of ``agent.py`` may be written. It proves
that conftest imports cleanly, the factories default every field, the fake LLM
pops exactly one response per call, and the clock is injectable.
"""

from __future__ import annotations

import conftest
import pytest

from src import clock
from src.models import GapType

pytestmark = pytest.mark.fast


def test_conftest_imports_and_defaults_every_field():
    page = conftest.make_page()
    issue = conftest.make_issue()
    audit = conftest.make_audit()
    serp = conftest.make_serp_result()
    competitor = conftest.make_competitor_page()
    keyword = conftest.make_keyword()
    cluster = conftest.make_cluster()
    gap = conftest.make_gap()
    item = conftest.make_backlog_item()

    assert page.url and page.title and page.h1_tags
    assert issue.issue_type and issue.severity
    assert audit.pages and audit.site_score > 0
    assert serp.domain == "moneysavingexpert.com"
    assert competitor.schema_types
    assert keyword.cluster_id
    assert cluster.keywords
    assert gap.gap_type == GapType.NO_PAGE
    assert item.item_id == "BL-0001"


def test_fake_llm_pops_one_response_per_call():
    llm = conftest.FakeLLM(["first", "second"])
    assert llm([{"role": "user", "content": "a"}]) == "first"
    assert llm([{"role": "user", "content": "b"}]) == "second"
    assert llm.count == 2
    assert len(llm.calls) == 2


def test_fake_llm_fails_loudly_when_exhausted():
    llm = conftest.FakeLLM([])
    with pytest.raises(pytest.fail.Exception):
        llm([{"role": "user", "content": "a"}])


def test_clock_is_injectable_and_utc(inject_clock):
    inject_clock("2026-11-16T09:00:00+00:00", step=60)
    first = clock.now()
    second = clock.now()
    assert first.isoformat() == "2026-11-16T09:00:00+00:00"
    assert (second - first).total_seconds() == 60
    assert first.tzinfo is not None


def test_write_guard_blocks_escape(tmp_path):
    with pytest.raises(pytest.fail.Exception), conftest.assert_write_paths_under(tmp_path):
        (tmp_path / "outside.txt").write_text("nope", encoding="utf-8")


def test_write_guard_allows_out_and_logs(tmp_path):
    with conftest.assert_write_paths_under(tmp_path) as written:
        (tmp_path / "out").mkdir()
        (tmp_path / "logs").mkdir()
        (tmp_path / "out" / "report.md").write_text("ok", encoding="utf-8")
        (tmp_path / "logs" / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    assert len(written) == 2
