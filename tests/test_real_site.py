"""Real-site regression: the landc.co.uk crawl of 2026-11-17 as a fixture.

The audit fixture comes from the live run recorded in
``out/run-20261117T143756Z/``. These tests pin the properties that crawl
exposed: the gap engine must not collapse into one schema warning per page,
and schema must be demand-relevant to keyword clusters.
"""

from __future__ import annotations

import pytest

from src import config
from src.audit_adapter import load_fixture
from src.backlog import build_backlog
from src.gap import analyze
from src.models import GapType
from src.pipeline import (
    build_clusters,
    build_keywords,
    load_profile,
    money_keywords_for,
)

pytestmark = pytest.mark.fast

LANDC_FIXTURE = config.FIXTURES_DIR / "landc_audit.json"


@pytest.fixture
def landc():
    profile = load_profile(config.PROFILES_DIR / "landc.json")
    audit = load_fixture(LANDC_FIXTURE, url=profile.base_url)
    clusters = build_clusters(build_keywords(profile))
    return profile, audit, clusters


def test_landc_gap_distribution_is_not_degenerate(landc):
    profile, audit, clusters = landc
    gaps = analyze(audit, clusters, cities=profile.cities)
    schema = [g for g in gaps if g.gap_type == GapType.SCHEMA_MISSING]
    others = [g for g in gaps if g.gap_type != GapType.SCHEMA_MISSING]
    assert others, "expected at least one non-schema gap"
    assert len(schema) / len(gaps) <= 0.94, (
        f"schema share {len(schema)}/{len(gaps)} is the degenerate pattern "
        "the gap engine was redesigned to avoid"
    )


def test_landc_schema_gaps_only_flag_cluster_relevant_pages(landc):
    profile, audit, clusters = landc
    gaps = analyze(audit, clusters, cities=profile.cities)
    targets = {g.target for g in gaps if g.gap_type == GapType.SCHEMA_MISSING}
    for irrelevant in (
        "https://www.landc.co.uk/about-us/our-awards",
        "https://www.landc.co.uk/about-us/list-of-lenders",
        "https://www.landc.co.uk/contact-us/supporting-our-customers",
    ):
        assert irrelevant not in targets


def test_landc_backlog_is_not_schema_flooded(landc):
    profile, audit, clusters = landc
    gaps = analyze(audit, clusters, cities=profile.cities)
    backlog = build_backlog(gaps, money_keywords=money_keywords_for(profile))
    schema_items = [i for i in backlog if i.gap_type == GapType.SCHEMA_MISSING.value]
    assert len(schema_items) == 1
    assert schema_items[0].evidence["page_count"] == len(
        {g.target for g in gaps if g.gap_type == GapType.SCHEMA_MISSING}
    )
    assert any(item.gap_type != GapType.SCHEMA_MISSING.value for item in backlog[:3])


def test_remortgage_calculator_cluster_maps_to_no_weak_page(landc):
    from src.gap import candidate_page

    profile, audit, clusters = landc
    cluster = next(c for c in clusters if c.head_term == "remortgage calculator")
    candidate = candidate_page(cluster, list(audit.pages))
    assert candidate is None or "calculator" in candidate.url
    gaps = analyze(audit, clusters, cities=profile.cities, gsc_demand=None)
    remortgage = [g for g in gaps if g.keyword == "remortgage calculator"]
    assert all(g.gap_type != GapType.WEAK_PAGE for g in remortgage)
