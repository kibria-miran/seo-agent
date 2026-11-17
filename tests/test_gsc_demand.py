"""GSC clicks/impressions/CTR/position flow through the pipeline (C1)."""

from __future__ import annotations

import pytest
from conftest import make_audit, make_cluster, make_keyword, make_page
from test_report_determinism import render as _render

from src.backlog import build_backlog
from src.gap import analyze
from src.models import GapType
from src.pipeline import gsc_demand_for
from src.sources.gsc_csv import GscCsvSource
from src.store import Store

pytestmark = pytest.mark.fast

BASE = "https://example.co.uk"


def test_to_keywords_carries_gsc_metrics():
    items = [
        {
            "keyword": "remortgage calculator",
            "clicks": 42.0,
            "impressions": 1000.0,
            "ctr": 4.2,
            "position": 3.5,
        }
    ]
    (keyword,) = GscCsvSource.to_keywords(items)
    assert keyword.gsc_clicks == 42.0
    assert keyword.gsc_impressions == 1000.0
    assert keyword.gsc_ctr == 4.2
    assert keyword.gsc_position == 3.5


def test_to_keywords_tolerates_missing_metrics():
    (keyword,) = GscCsvSource.to_keywords([{"keyword": "remortgage advice"}])
    assert keyword.gsc_clicks is None
    assert keyword.gsc_impressions is None


def test_gsc_demand_for_filters_non_gsc_keywords():
    keywords = [make_keyword(keyword="plain term", source="suggest")]
    assert gsc_demand_for(keywords) == {}


def test_gap_evidence_carries_aggregated_gsc_demand():
    cluster = make_cluster(
        cluster_id="c-rem",
        head_term="remortgage advice",
        keywords=["remortgage advice", "remortgage help"],
    )
    audit = make_audit(pages=[make_page(url=f"{BASE}/", page_score=100.0)], issues=[])
    demand = {
        "remortgage advice": {"clicks": 10.0, "impressions": 500.0, "ctr": 0.02, "position": 4.0},
        "remortgage help": {"clicks": 5.0, "impressions": 300.0, "ctr": None, "position": 6.0},
        "unrelated term": {"clicks": 99.0, "impressions": 9999.0, "ctr": 0.5, "position": 1.0},
    }
    gaps = analyze(audit, [cluster], gsc_demand=demand)
    coverage = [g for g in gaps if g.gap_type != GapType.SCHEMA_MISSING]
    assert len(coverage) == 1
    gsc = coverage[0].evidence["gsc"]
    assert gsc["clicks"] == 15.0
    assert gsc["impressions"] == 800.0
    assert gsc["queries"] == 2
    assert gsc["ctr"] == pytest.approx(15.0 / 800.0)
    assert gsc["position"] == 4.0


def test_gap_without_gsc_demand_has_no_gsc_evidence():
    cluster = make_cluster(cluster_id="c-rem", head_term="remortgage advice",
                           keywords=["remortgage advice"])
    audit = make_audit(pages=[make_page(url=f"{BASE}/", page_score=100.0)], issues=[])
    gaps = analyze(audit, [cluster])
    coverage = [g for g in gaps if g.gap_type != GapType.SCHEMA_MISSING]
    assert "gsc" not in coverage[0].evidence


def test_backlog_items_carry_gsc_evidence():
    cluster = make_cluster(cluster_id="c-rem", head_term="remortgage advice",
                           keywords=["remortgage advice"])
    audit = make_audit(pages=[make_page(url=f"{BASE}/", page_score=100.0)], issues=[])
    demand = {
        "remortgage advice": {"clicks": 10.0, "impressions": 500.0, "ctr": 0.02, "position": 4.0},
    }
    gaps = analyze(audit, [cluster], gsc_demand=demand)
    backlog = build_backlog(gaps)
    assert backlog
    assert backlog[0].evidence["gsc"]["impressions"] == 500.0


def test_store_roundtrip_preserves_gsc_metrics():
    keywords = [
        make_keyword(
            keyword="remortgage advice",
            source="gsc_csv",
            gsc_clicks=10.0,
            gsc_impressions=500.0,
            gsc_ctr=0.02,
            gsc_position=4.5,
        )
    ]
    with Store(":memory:") as store:
        store.start_run("run-t", url="https://example.co.uk")
        store.save_keywords("run-t", keywords)
        (loaded,) = store.load_keywords("run-t")
    assert loaded.gsc_clicks == 10.0
    assert loaded.gsc_impressions == 500.0
    assert loaded.gsc_ctr == 0.02
    assert loaded.gsc_position == 4.5


def test_report_renders_gsc_demand_section_when_data_present():
    keywords = [
        make_keyword(keyword="remortgage advice", gsc_clicks=10.0,
                     gsc_impressions=500.0, gsc_ctr=0.02, gsc_position=4.5),
        make_keyword(keyword="low impressions", gsc_clicks=0.0,
                     gsc_impressions=10.0, gsc_ctr=0.0, gsc_position=12.0),
    ]
    markdown = _render(keywords=keywords)
    assert "## GSC demand (from your export)" in markdown
    assert "remortgage advice" in markdown
    assert markdown.index("remortgage advice") < markdown.index("low impressions")


def test_report_omits_gsc_demand_section_without_data():
    markdown = _render(keywords=[make_keyword(keyword="remortgage advice")])
    assert "GSC demand" not in markdown


def test_gsc_demand_boosts_priority_through_the_pipeline(tmp_path, inject_clock, monkeypatch):
    inject_clock("2026-11-16T09:00:00+00:00")
    csv_path = tmp_path / "Queries.csv"
    csv_path.write_text(
        "Top queries,Clicks,Impressions,CTR,Position\n"
        "bad credit mortgage,50,5000,1.0%,4.2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SEO_AGENT_GSC_CSV", str(csv_path))

    from src import config
    from src.pipeline import load_profile, run_deterministic

    profile = load_profile(config.PROFILES_DIR / "site.json")
    report = run_deterministic(
        profile,
        fixture_path=config.FIXTURES_DIR / "own_site_audit.json",
        run_id="run-gsc-it",
        db_path=tmp_path / "seo.db",
        out_root=tmp_path / "out",
        with_sources=True,
    )
    by_target = {item.target: item for item in report.backlog}
    boosted = by_target["/bad-credit-mortgage"]
    plain = by_target["/mortgage-broker-near-me"]
    assert boosted.gap_type == GapType.NO_PAGE.value
    assert plain.gap_type == GapType.NO_PAGE.value
    assert boosted.evidence["gsc"]["impressions"] == 5000.0
    assert "gsc" not in plain.evidence
    assert boosted.priority == round(plain.priority * config.GSC_BOOST_TIER_1, 4)
    assert report.backlog.index(boosted) < report.backlog.index(plain)
