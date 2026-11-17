"""Gap analysis: table-driven coverage of every gap type (section 7/8.3)."""

from __future__ import annotations

import pytest
from conftest import (
    make_audit,
    make_cluster,
    make_competitor_page,
    make_page,
    make_serp_result,
)

from src.gap import analyze, candidate_page, competitor_matches, serp_matches
from src.models import GapType

pytestmark = pytest.mark.fast

BASE = "https://clearpath-mortgage.co.uk"


def home(**overrides):
    data = {"url": f"{BASE}/", "title": "Home", "h1_tags": ["Welcome"]}
    data.update(overrides)
    return make_page(**data)


# ---------------------------------------------------------------------------
# NO_PAGE
# ---------------------------------------------------------------------------


def test_no_page_when_nothing_targets_the_cluster():
    audit = make_audit(pages=[home()], issues=[])
    cluster = make_cluster(
        cluster_id="c-bad",
        head_term="bad credit mortgage",
        keywords=["bad credit mortgage", "bad credit home loan"],
    )
    gaps = analyze(audit, [cluster])
    coverage = [g for g in gaps if g.gap_type != GapType.SCHEMA_MISSING]
    assert len(coverage) == 1
    gap = coverage[0]
    assert gap.gap_type == GapType.NO_PAGE
    assert gap.keyword == "bad credit mortgage"
    assert gap.target == "/bad-credit-mortgage"
    assert gap.sources == ["keywords"]
    assert gap.evidence["cluster_keywords"] == ["bad credit home loan", "bad credit mortgage"]
    assert gap.evidence["pages"] == [f"{BASE}/"]


def test_covered_cluster_produces_no_gap():
    audit = make_audit(pages=[home(title="Free Mortgage Advice from ClearPath")], issues=[])
    cluster = make_cluster(head_term="free mortgage advice")
    assert analyze(audit, [cluster]) == []


def test_h1_alone_is_enough_for_coverage():
    page = home(title="Homepage", h1_tags=["Free mortgage advice"])
    assert analyze(make_audit(pages=[page]), [make_cluster(head_term="free mortgage advice")]) == []


# ---------------------------------------------------------------------------
# WEAK_PAGE
# ---------------------------------------------------------------------------


def test_weak_page_when_slug_matches_but_title_and_h1_miss_head_term():
    page = make_page(
        url=f"{BASE}/remortgage-calculator",
        title="Remortgage Advice | ClearPath",
        h1_tags=["Remortgage advice"],
    )
    cluster = make_cluster(
        cluster_id="c-calc", head_term="remortgage calculator", keywords=["remortgage calculator"]
    )
    gaps = [g for g in analyze(make_audit(pages=[page]), [cluster])
            if g.gap_type == GapType.WEAK_PAGE]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_type == GapType.WEAK_PAGE
    assert gap.target == page.url
    assert gap.sources == []
    assert gap.evidence["page"] == page.url
    assert gap.evidence["title"] == "Remortgage Advice | ClearPath"


def test_candidate_page_uses_url_slug_and_is_deterministic():
    alpha = make_page(url=f"{BASE}/remortgage-calculator", title="A", h1_tags=[])
    beta = make_page(url=f"{BASE}/remortgage", title="B", h1_tags=[])
    cluster = make_cluster(head_term="remortgage calculator")
    assert candidate_page(cluster, [beta, alpha]) is alpha
    assert candidate_page(cluster, [alpha, beta]) is alpha


# ---------------------------------------------------------------------------
# LOCAL_MISSING
# ---------------------------------------------------------------------------


def test_local_missing_when_city_has_no_page():
    cluster = make_cluster(
        cluster_id="c-manc",
        head_term="mortgage advice manchester",
        keywords=["mortgage advice manchester"],
    )
    gaps = analyze(make_audit(pages=[home()]), [cluster])
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_type == GapType.LOCAL_MISSING
    assert gap.evidence["city"] == "Manchester"
    assert gap.evidence["service"] == "mortgage advice manchester"
    assert gap.target == "/mortgage-advice-manchester"
    assert gap.sources == ["keywords", "cities"]


def test_local_page_that_covers_city_is_not_a_gap():
    page = make_page(
        url=f"{BASE}/mortgage-advice-manchester",
        title="Mortgage Advice Manchester",
        h1_tags=["Mortgage advice in Manchester"],
    )
    cluster = make_cluster(head_term="mortgage advice manchester")
    gaps = analyze(make_audit(pages=[page]), [cluster])
    assert all(g.gap_type != GapType.SCHEMA_MISSING for g in gaps)


# ---------------------------------------------------------------------------
# COMP_COVERS
# ---------------------------------------------------------------------------


def test_comp_covers_when_two_competitor_domains_cover_an_uncovered_topic():
    competitors = [
        make_competitor_page(
            domain="habito.com",
            url="https://habito.com/bad-credit-mortgages",
            title="Bad credit mortgage help",
            h_tags={"h1": ["Bad credit mortgages"]},
        ),
        make_competitor_page(
            domain="trussle.com",
            url="https://trussle.com/bad-credit",
            title="Bad credit mortgage guide",
            h_tags={"h1": ["Bad credit mortgage guide"]},
        ),
    ]
    cluster = make_cluster(cluster_id="c-bad", head_term="bad credit mortgage")
    gaps = analyze(make_audit(pages=[home()]), [cluster], competitors)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_type == GapType.COMP_COVERS
    assert gap.sources == ["keywords", "habito.com", "trussle.com"]
    assert gap.evidence["domains"] == ["habito.com", "trussle.com"]
    assert gap.evidence["competitors"] == [
        "https://habito.com/bad-credit-mortgages",
        "https://trussle.com/bad-credit",
    ]


def test_single_competitor_is_evidence_for_no_page_not_a_comp_covers():
    competitor = make_competitor_page(
        domain="habito.com",
        title="Bad credit mortgage help",
        h_tags={"h1": ["Bad credit mortgages"]},
    )
    cluster = make_cluster(cluster_id="c-bad", head_term="bad credit mortgage")
    gaps = analyze(make_audit(pages=[home()]), [cluster], [competitor])
    gap = gaps[0]
    assert gap.gap_type == GapType.NO_PAGE
    assert gap.sources == ["keywords", "competitors"]
    assert gap.evidence["competitors"] == [competitor.url]


# ---------------------------------------------------------------------------
# SCHEMA_MISSING
# ---------------------------------------------------------------------------


def test_schema_missing_for_a_page_with_no_required_schema():
    page = make_page(url=f"{BASE}/no-schema", schema_types=[])
    cluster = make_cluster(cluster_id="c-ns", head_term="no schema")
    gaps = [g for g in analyze(make_audit(pages=[page]), [cluster])
            if g.gap_type == GapType.SCHEMA_MISSING]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_type == GapType.SCHEMA_MISSING
    assert gap.target == page.url
    assert gap.sources == []
    assert gap.evidence["required"] == ["LocalBusiness", "FinancialService", "FAQPage"]


def test_unrelated_schema_still_counts_as_missing():
    page = make_page(url=f"{BASE}/website-only", schema_types=["WebSite"])
    cluster = make_cluster(cluster_id="c-web", head_term="website only")
    gaps = analyze(make_audit(pages=[page]), [cluster])
    assert any(g.gap_type == GapType.SCHEMA_MISSING for g in gaps)


@pytest.mark.parametrize("schema", ["LocalBusiness", "FinancialService", "FAQPage"])
def test_any_required_schema_is_enough(schema):
    page = make_page(url=f"{BASE}/ok", schema_types=[schema])
    cluster = make_cluster(cluster_id="c-ok", head_term="ok")
    gaps = analyze(make_audit(pages=[page]), [cluster])
    assert all(g.gap_type != GapType.SCHEMA_MISSING for g in gaps)


def test_schema_required_list_can_be_overridden():
    page = make_page(url=f"{BASE}/ok", schema_types=["FinancialService"])
    cluster = make_cluster(cluster_id="c-ok", head_term="ok")
    gaps = [g for g in analyze(make_audit(pages=[page]), [cluster], required_schema=("FAQPage",))
            if g.gap_type == GapType.SCHEMA_MISSING]
    assert gaps[0].gap_type == GapType.SCHEMA_MISSING
    assert gaps[0].evidence["required"] == ["FAQPage"]


def test_non_200_pages_are_skipped_for_schema():
    page = make_page(url=f"{BASE}/missing", status_code=404, schema_types=[])
    assert analyze(make_audit(pages=[page]), []) == []


# ---------------------------------------------------------------------------
# SERP evidence
# ---------------------------------------------------------------------------


def test_serp_results_add_evidence_and_a_source():
    cluster = make_cluster(cluster_id="c-bad", head_term="bad credit mortgage")
    serp = [
        make_serp_result(
            query="bad credit mortgage",
            url="https://example.com/bad-credit",
            title="Bad credit mortgage guide",
            domain="example.com",
        )
    ]
    gap = analyze(make_audit(pages=[home()]), [cluster], serp=serp)[0]
    assert gap.gap_type == GapType.NO_PAGE
    assert "serp" in gap.sources
    assert gap.evidence["serp"] == ["https://example.com/bad-credit"]


def test_competitor_matches_is_sorted_and_stable():
    a = make_competitor_page(domain="b.com", url="https://b.com/x", title="Bad credit mortgage")
    b = make_competitor_page(domain="a.com", url="https://a.com/x", title="Bad credit mortgage")
    assert [c.domain for c in competitor_matches("bad credit mortgage", [a, b])] == ["a.com", "b.com"]


def test_serp_matches_is_sorted_and_stable():
    a = make_serp_result(query="z", rank=2, title="Bad credit mortgage", url="https://b.com/x")
    b = make_serp_result(query="z", rank=1, title="Bad credit mortgage", url="https://a.com/x")
    assert [r.rank for r in serp_matches("bad credit mortgage", [a, b])] == [1, 2]


# ---------------------------------------------------------------------------
# Determinism and evidence invariants
# ---------------------------------------------------------------------------


def test_analysis_is_deterministic_and_order_independent():
    audit = make_audit(pages=[home(), make_page(url=f"{BASE}/no-schema", schema_types=[])])
    clusters = [
        make_cluster(cluster_id="c-b", head_term="bad credit mortgage"),
        make_cluster(cluster_id="c-a", head_term="mortgage advice manchester"),
    ]
    competitors = [
        make_competitor_page(domain="habito.com", title="Bad credit mortgage"),
        make_competitor_page(domain="trussle.com", title="Bad credit mortgage"),
    ]
    first = [gap.model_dump_json() for gap in analyze(audit, clusters, competitors)]
    second = [
        gap.model_dump_json()
        for gap in analyze(audit, list(reversed(clusters)), list(reversed(competitors)))
    ]
    assert first == second


def test_every_gap_carries_evidence():
    audit = make_audit(
        pages=[
            home(),
            make_page(url=f"{BASE}/remortgage-calculator", title="Remortgage Advice", schema_types=[]),
        ]
    )
    clusters = [
        make_cluster(cluster_id="c-a", head_term="bad credit mortgage"),
        make_cluster(cluster_id="c-b", head_term="remortgage calculator"),
        make_cluster(cluster_id="c-c", head_term="mortgage advice manchester"),
    ]
    for gap in analyze(audit, clusters):
        assert gap.evidence, f"{gap.gap_type} has no evidence"


def test_duplicate_cluster_ids_are_deduplicated_deterministically():
    one = make_cluster(cluster_id="same", head_term="zeta topic")
    two = make_cluster(cluster_id="same", head_term="alpha topic")
    gaps = analyze(make_audit(pages=[home()]), [one, two])
    assert len(gaps) == 1
    # Sorted by (cluster_id, head_term), so the alphabetically first head wins.
    assert gaps[0].keyword == "alpha topic"


def test_no_page_evidence_lists_nearest_pages_not_full_census():
    from conftest import make_audit, make_cluster, make_page

    pages = [
        make_page(url=f"https://example.co.uk/{slug}", title="placeholder", h1_tags=[])
        for slug in [
            "bad-credit-mortgage",
            "first-time-buyer",
            "buy-to-let",
            "remortgage",
            "free-mortgage-advice",
            "unrelated-page",
        ]
    ]
    audit = make_audit(url="https://example.co.uk", pages=pages)
    cluster = make_cluster(cluster_id="c1", keywords=["home loan guide"], head_term="home loan guide")
    gaps = analyze(audit, [cluster], cities=["London"])
    no_page = next(g for g in gaps if g.gap_type.value == "NO_PAGE")
    listed = no_page.evidence["pages"]
    assert listed == sorted(listed)
    assert len(listed) == 5
    assert "https://example.co.uk/unrelated-page" not in listed


def test_schema_gap_only_on_cluster_relevant_pages():
    relevant = make_page(url=f"{BASE}/remortgage-calculator", title="Calc", schema_types=[])
    irrelevant = make_page(url=f"{BASE}/about-our-team", title="Team", schema_types=[])
    cluster = make_cluster(cluster_id="c-rc", head_term="remortgage calculator")
    gaps = [g for g in analyze(make_audit(pages=[relevant, irrelevant]), [cluster])
            if g.gap_type == GapType.SCHEMA_MISSING]
    assert [g.target for g in gaps] == [relevant.url]


def test_no_clusters_means_no_schema_gaps():
    page = make_page(url=f"{BASE}/some-page", schema_types=[])
    assert analyze(make_audit(pages=[page]), []) == []
