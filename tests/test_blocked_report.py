"""Zero-block scrape outcome is surfaced as counts, and in the report (C3)."""

from __future__ import annotations

import pytest
from conftest import make_profile
from test_report_determinism import render

from src import pipeline
from src.sources.base import SourceResult
from src.store import Store
from src.trace import TraceWriter

pytestmark = pytest.mark.fast


def test_zero_results_are_counted_not_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.sources.suggest.SuggestSource.collect",
        lambda self, seed, **kwargs: SourceResult(source="suggest", query=seed, items=()),
    )
    monkeypatch.setattr(
        "src.sources.serp.SerpSource.collect",
        lambda self, query, **kwargs: SourceResult(source="serp", query=query, items=()),
    )
    monkeypatch.setattr(
        "src.sources.competitor.mine_competitors",
        lambda profile, store, trace: [],
    )
    profile = make_profile()
    with Store(":memory:") as store:
        _keywords, _serp, _pages, counts = pipeline.mine_scraping_sources(
            profile, store, TraceWriter(tmp_path / "trace.jsonl", "zero-block-test")
        )
    assert counts["suggest"] == 0
    assert counts["suggest_empty"] >= 1
    assert counts["serp"] == 0
    assert counts["serp_empty"] == len(profile.target_keywords)


def test_report_flags_possible_block_when_zero_attempts_empty():
    markdown = render(
        budgets={
            "sources": {
                "suggest": 0,
                "serp": 0,
                "gsc_csv": 0,
                "gsc_pages": 0,
                "competitor_pages": 0,
                "serp_empty": 3,
            }
        }
    )
    assert "possible bot block" in markdown
    assert "3 attempt(s) returned zero results" in markdown
