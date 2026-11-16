"""Scraping is ToS-grey and off unless --with-scraping is passed (owner Q5)."""

from __future__ import annotations

import pytest
from conftest import make_keyword, make_profile

import src.pipeline as pipeline

pytestmark = pytest.mark.fast

FIXTURE = "tests/fixtures/own_site_audit.json"


def test_default_run_never_touches_sources(tmp_path, inject_clock, monkeypatch):
    inject_clock("2026-11-16T09:00:00+00:00")
    monkeypatch.setattr(
        pipeline, "mine_scraping_sources",
        lambda *a, **k: pytest.fail("scraping must not run by default"),
    )
    monkeypatch.setattr(
        pipeline, "mine_file_sources",
        lambda *a, **k: pytest.fail("file sources must not run by default"),
    )
    report = pipeline.run_deterministic(
        make_profile(),
        fixture_path=FIXTURE,
        run_id="run-policy-default",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
    )
    assert report.budgets["fetches"] == 0
    assert "sources" not in report.budgets


def test_with_sources_uses_file_ingest_only(tmp_path, inject_clock, monkeypatch):
    inject_clock("2026-11-16T09:00:00+00:00")
    monkeypatch.setattr(
        pipeline, "mine_scraping_sources",
        lambda *a, **k: pytest.fail("with_sources must not enable scraping"),
    )
    monkeypatch.setattr(
        pipeline,
        "mine_file_sources",
        lambda profile, store, trace: (
            [make_keyword(keyword="gsc kw", source="gsc_csv", gsc_impressions=10.0)],
            {"gsc_csv": 1},
        ),
    )
    monkeypatch.setattr(pipeline, "mine_gsc_pages", lambda store, trace: ({}, "dep_unmet"))
    report = pipeline.run_deterministic(
        make_profile(),
        fixture_path=FIXTURE,
        run_id="run-policy-file",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
        with_sources=True,
    )
    assert report.budgets["sources"]["gsc_csv"] == 1
    assert report.budgets["sources"]["suggest"] == 0


def test_with_scraping_enables_scraping(tmp_path, inject_clock, monkeypatch):
    inject_clock("2026-11-16T09:00:00+00:00")
    monkeypatch.setattr(
        pipeline,
        "mine_scraping_sources",
        lambda profile, store, trace: (
            [make_keyword(keyword="scraped kw", source="suggest")],
            [],
            [],
            {"suggest": 1, "serp": 0, "competitor_pages": 0,
             "suggest_empty": 0, "serp_empty": 0, "fetches": 2},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "mine_file_sources",
        lambda *a, **k: pytest.fail("with_scraping must not enable file sources"),
    )
    report = pipeline.run_deterministic(
        make_profile(),
        fixture_path=FIXTURE,
        run_id="run-policy-scraping",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
        with_scraping=True,
    )
    assert report.budgets["sources"]["suggest"] == 1
    assert report.budgets["fetches"] == 2
