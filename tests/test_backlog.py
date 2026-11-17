"""Backlog scoring, tie-breaks, determinism and caps (section 8.4)."""

from __future__ import annotations

import pytest
from conftest import make_gap

from src import config
from src.backlog import (
    build_backlog,
    confidence_for,
    effort_for,
    impact_for,
    priority_for,
)
from src.models import GapType

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------


def test_priority_formula_no_page_money_keyword():
    gap = make_gap(keyword="Remortgage Advice", sources=["suggest"])
    assert impact_for(gap, ["remortgage advice"]) == config.IMPACT_CRITICAL
    assert confidence_for(gap) == config.CONFIDENCE_SINGLE_SOURCE
    assert effort_for(gap) == config.EFFORT_PAGE
    assert priority_for(gap, ["remortgage advice"]) == 0.5


def test_priority_formula_no_page_non_money_keyword():
    gap = make_gap(keyword="bad credit mortgage", sources=["suggest"])
    assert impact_for(gap, ["remortgage advice"]) == config.IMPACT_WARNING
    assert priority_for(gap, ["remortgage advice"]) == 0.3333


def test_priority_multi_source_confidence():
    gap = make_gap(sources=["suggest", "serp", "gsc"])
    assert confidence_for(gap) == config.CONFIDENCE_MULTI_SOURCE
    assert priority_for(gap) == 0.5333


def test_priority_dual_source_confidence():
    gap = make_gap(sources=["suggest", "serp"])
    assert confidence_for(gap) == config.CONFIDENCE_DUAL_SOURCE
    assert priority_for(gap) == 0.4333


def test_priority_reads_sources_from_evidence_when_field_is_empty():
    gap = make_gap(sources=[], evidence={"sources": ["suggest", "serp", "gsc"]})
    assert gap.source_count == 3
    assert confidence_for(gap) == config.CONFIDENCE_MULTI_SOURCE


def test_weak_page_is_an_audit_rule_with_effort_one():
    gap = make_gap(gap_type=GapType.WEAK_PAGE, sources=[])
    assert impact_for(gap) == config.IMPACT_WARNING
    assert confidence_for(gap) == config.CONFIDENCE_AUDIT
    assert effort_for(gap) == config.EFFORT_META
    assert priority_for(gap) == 2.0


def test_schema_missing_is_an_audit_rule_with_effort_two():
    gap = make_gap(gap_type=GapType.SCHEMA_MISSING, sources=[])
    assert confidence_for(gap) == config.CONFIDENCE_AUDIT
    assert effort_for(gap) == config.EFFORT_SCHEMA
    assert priority_for(gap) == 1.0


def test_local_missing_impact_and_effort():
    gap = make_gap(gap_type=GapType.LOCAL_MISSING, keyword="mortgage advice leeds")
    assert impact_for(gap) == config.IMPACT_WARNING
    assert effort_for(gap) == config.EFFORT_PAGE
    assert priority_for(gap) == 0.3333


def test_competitor_coverage_uses_source_count_for_confidence():
    gap = make_gap(
        gap_type=GapType.COMP_COVERS,
        sources=["habito.com", "trussle.com", "lcplc.co.uk"],
    )
    assert confidence_for(gap) == config.CONFIDENCE_MULTI_SOURCE
    assert priority_for(gap) == 0.5333


def test_explicit_severity_overrides_the_default_impact():
    gap = make_gap(evidence={"severity": "CRITICAL"})
    assert impact_for(gap) == config.IMPACT_CRITICAL


def test_money_keyword_match_is_case_and_space_insensitive():
    gap = make_gap(keyword="  FREE   Mortgage Advice ")
    assert impact_for(gap, ["free mortgage advice"]) == config.IMPACT_CRITICAL


# ---------------------------------------------------------------------------
# Ordering and determinism
# ---------------------------------------------------------------------------


def test_backlog_is_sorted_by_priority_descending():
    gaps = [
        make_gap(keyword="normal", gap_type=GapType.NO_PAGE, sources=["suggest"]),
        make_gap(keyword="remortgage advice", gap_type=GapType.NO_PAGE, sources=["suggest"]),
        make_gap(keyword="weak", gap_type=GapType.WEAK_PAGE, sources=[]),
        make_gap(keyword="schema", gap_type=GapType.SCHEMA_MISSING, sources=[]),
    ]
    items = build_backlog(gaps, money_keywords=["remortgage advice"])
    priorities = [item.priority for item in items]
    assert priorities == sorted(priorities, reverse=True)
    assert items[0].gap_type == GapType.WEAK_PAGE.value
    assert items[1].gap_type == GapType.SCHEMA_MISSING.value


def test_tie_break_prefers_lowest_effort():
    weak = make_gap(
        keyword="weak",
        gap_type=GapType.WEAK_PAGE,
        evidence={"severity": "INFO"},
        sources=[],
    )
    schema = make_gap(keyword="schema", gap_type=GapType.SCHEMA_MISSING, sources=[])
    assert priority_for(weak) == priority_for(schema) == 1.0
    items = build_backlog([schema, weak])
    assert [item.gap_type for item in items] == ["WEAK_PAGE", "SCHEMA_MISSING"]


def test_tie_break_then_alphabetical_by_target():
    zeta = make_gap(keyword="zeta topic", target="zeta.co.uk", sources=["suggest"])
    alpha = make_gap(keyword="alpha topic", target="alpha.co.uk", sources=["suggest"])
    items = build_backlog([zeta, alpha])
    assert [item.target for item in items] == ["alpha.co.uk", "zeta.co.uk"]


def test_deduplicates_identical_gap_keeping_the_best_priority():
    weak = make_gap(keyword="remortgage", sources=["suggest"])
    strong = make_gap(keyword="remortgage", sources=["suggest", "serp", "gsc"])
    items = build_backlog([weak, strong])
    assert len(items) == 1
    assert items[0].priority == 0.5333
    assert items[0].confidence == config.CONFIDENCE_MULTI_SOURCE


def test_input_order_does_not_change_the_output():
    gaps = [
        make_gap(keyword="a topic", target="a.co.uk", sources=["suggest"]),
        make_gap(keyword="b topic", target="b.co.uk", gap_type=GapType.LOCAL_MISSING),
        make_gap(keyword="c topic", gap_type=GapType.WEAK_PAGE, sources=[]),
        make_gap(keyword="d topic", gap_type=GapType.SCHEMA_MISSING, sources=[]),
    ]
    forward = [item.model_dump() for item in build_backlog(gaps)]
    backward = [item.model_dump() for item in build_backlog(list(reversed(gaps)))]
    assert forward == backward


def test_repeated_builds_are_byte_identical():
    gaps = [
        make_gap(keyword="remortgage advice"),
        make_gap(keyword="bad credit", gap_type=GapType.LOCAL_MISSING),
        make_gap(keyword="schema", gap_type=GapType.SCHEMA_MISSING),
    ]
    first = [item.model_dump_json() for item in build_backlog(gaps)]
    second = [item.model_dump_json() for item in build_backlog(gaps)]
    assert first == second


# ---------------------------------------------------------------------------
# Caps, ids, status, evidence
# ---------------------------------------------------------------------------


def test_backlog_is_capped_at_max_backlog_by_default():
    gaps = [make_gap(keyword=f"topic {index:02d}", sources=["suggest"]) for index in range(40)]
    items = build_backlog(gaps)
    assert len(items) == config.MAX_BACKLOG


def test_backlog_honours_an_explicit_cap_and_assigns_stable_ids():
    gaps = [make_gap(keyword=f"topic {index:02d}", sources=["suggest"]) for index in range(10)]
    items = build_backlog(gaps, max_items=3)
    assert len(items) == 3
    assert [item.item_id for item in items] == ["BL-0001", "BL-0002", "BL-0003"]


def test_zero_cap_returns_empty():
    assert build_backlog([make_gap()], max_items=0) == []


def test_empty_gaps_returns_empty():
    assert build_backlog([]) == []


def test_items_start_open_and_carry_evidence():
    gap = make_gap(evidence={"serp": ["https://example.co.uk"], "severity": "INFO"})
    item = build_backlog([gap])[0]
    assert item.status == "open"
    assert item.evidence["serp"] == ["https://example.co.uk"]


@pytest.mark.parametrize(
    ("gap_type", "kind", "effort"),
    [
        (GapType.NO_PAGE, "create_page", 3),
        (GapType.LOCAL_MISSING, "create_local_page", 3),
        (GapType.COMP_COVERS, "create_page", 3),
        (GapType.WEAK_PAGE, "meta_fix", 1),
        (GapType.SCHEMA_MISSING, "schema", 2),
    ],
)
def test_gap_types_map_to_kind_and_effort(gap_type, kind, effort):
    item = build_backlog([make_gap(gap_type=gap_type, sources=[])])[0]
    assert item.kind == kind
    assert item.effort == effort
    assert item.title


def test_priority_rounding_is_stable_to_four_places():
    gap = make_gap(sources=["suggest", "serp", "gsc"])
    assert priority_for(gap) == round(priority_for(gap), 4)


# ---------------------------------------------------------------------------
# GSC demand weighting and schema umbrella grouping
# ---------------------------------------------------------------------------


def test_gsc_demand_boosts_priority():
    unboosted = make_gap(gap_type=GapType.NO_PAGE, sources=["suggest"])
    boosted = make_gap(
        gap_type=GapType.NO_PAGE,
        sources=["suggest"],
        evidence={"gsc": {"impressions": 5000.0, "clicks": 10.0}},
    )
    assert priority_for(boosted) > priority_for(unboosted)
    small = make_gap(
        gap_type=GapType.NO_PAGE,
        sources=["suggest"],
        evidence={"gsc": {"impressions": 50.0}},
    )
    none = make_gap(
        gap_type=GapType.NO_PAGE,
        sources=["suggest"],
        evidence={"gsc": {"impressions": 1.0}},
    )
    assert priority_for(small) > priority_for(none) > priority_for(unboosted) - 1e-9


def test_schema_findings_above_threshold_group_into_one_umbrella_item():
    gaps = [
        make_gap(gap_type=GapType.SCHEMA_MISSING, target=f"https://example.co.uk/p{i}", sources=[])
        for i in range(6)
    ]
    items = build_backlog(gaps, money_keywords=[])
    assert len(items) == 1
    item = items[0]
    assert item.gap_type == GapType.SCHEMA_MISSING.value
    assert item.evidence["page_count"] == 6
    assert item.evidence["pages"] == sorted(f"https://example.co.uk/p{i}" for i in range(6))
    assert item.effort == 6
    assert item.title == "Add missing schema to 6 keyword-relevant pages"


def test_schema_umbrella_carries_money_page_impact():
    pages = ["https://example.co.uk/money"] + [
        f"https://example.co.uk/p{i}" for i in range(5)
    ]
    gaps = [
        make_gap(gap_type=GapType.SCHEMA_MISSING, target=page, sources=[])
        for page in pages
    ]
    items = build_backlog(
        gaps, money_keywords=[], money_urls=["https://example.co.uk/money/"]
    )
    assert len(items) == 1
    item = items[0]
    assert item.impact == config.IMPACT_CRITICAL
    assert item.evidence["money_pages"] == ["https://example.co.uk/money"]
    assert item.evidence["money_page_count"] == 1
    assert item.effort == 6
    assert item.priority == round(config.IMPACT_CRITICAL * config.CONFIDENCE_AUDIT / 6, 4)
    assert "1 money pages" in item.title


def test_schema_umbrella_without_money_pages_stays_warning():
    gaps = [
        make_gap(gap_type=GapType.SCHEMA_MISSING, target=f"https://example.co.uk/p{i}", sources=[])
        for i in range(6)
    ]
    items = build_backlog(
        gaps, money_keywords=[], money_urls=["https://example.co.uk/money"]
    )
    assert len(items) == 1
    assert items[0].impact == config.IMPACT_WARNING
    assert items[0].evidence["money_pages"] == []
    assert items[0].evidence["money_page_count"] == 0


def test_schema_findings_at_or_below_threshold_stay_per_page():
    gaps = [
        make_gap(gap_type=GapType.SCHEMA_MISSING, target=f"https://example.co.uk/p{i}", sources=[])
        for i in range(3)
    ]
    items = build_backlog(gaps, money_keywords=[])
    assert len(items) == 3
    assert all(item.title.startswith("Add missing schema to https://") for item in items)
def test_tie_break_prefers_money_keyword_over_severity_match():
    money = make_gap(keyword="bad credit mortgage", sources=["suggest"])
    non_money = make_gap(
        keyword="unrelated topic",
        evidence={"severity": "CRITICAL"},
        sources=["suggest"],
    )
    assert priority_for(money, ["bad credit mortgage"]) == priority_for(non_money) == 0.5
    items = build_backlog([non_money, money], money_keywords=["bad credit mortgage"])
    assert [item.title for item in items] == [
        "Create a page targeting 'bad credit mortgage'",
        "Create a page targeting 'unrelated topic'",
    ]


def test_tie_break_then_gsc_impressions_desc():
    low = make_gap(
        keyword="low demand topic",
        evidence={"gsc": {"impressions": 2}},
        sources=["suggest"],
    )
    high = make_gap(
        keyword="high demand topic",
        evidence={"gsc": {"impressions": 9}},
        sources=["suggest"],
    )
    assert priority_for(low) == priority_for(high) == 0.3333
    items = build_backlog([low, high])
    assert [item.title for item in items] == [
        "Create a page targeting 'high demand topic'",
        "Create a page targeting 'low demand topic'",
    ]

# ---------------------------------------------------------------------------
# N-3 total order: shuffle invariance and terminal ties (Phase 2)
# ---------------------------------------------------------------------------


def _phase2_gaps():
    return [
        make_gap(keyword="capital one card", target="/zulu-capital-card",
                 evidence={"cluster_keywords": ["capital one card", "capital one card rates"]},
                 sources=["suggest"]),
        make_gap(keyword="beta capital card", target="/alpha-capital-card",
                 evidence={"cluster_keywords": ["beta capital card"]},
                 sources=["suggest"]),
        make_gap(keyword="bad credit mortgage", target="/bad-credit-mortgage",
                 evidence={"gsc": {"impressions": 2.0}}, sources=["suggest"]),
        make_gap(keyword="remortgage calculator", target="/remortgage-calculator",
                 evidence={"gsc": {"impressions": 9.0}}, sources=["suggest"]),
        make_gap(keyword="weak demand topic", gap_type=GapType.WEAK_PAGE, sources=[],
                 evidence={"severity": "INFO", "page": "https://example.co.uk/weak"}),
        make_gap(keyword="rival topic", target="/rival-topic",
                 sources=["habito.com"], gap_type=GapType.COMP_COVERS),
        make_gap(keyword="rival topic", target="/rival-topic", sources=["suggest"]),
        make_gap(keyword="dup topic", target="/dup-topic",
                 evidence={"pages": ["b.co.uk"]}, sources=["suggest"]),
        make_gap(keyword="dup topic", target="/dup-topic",
                 evidence={"pages": ["a.co.uk"]}, sources=["suggest"]),
        make_gap(keyword="schema", gap_type=GapType.SCHEMA_MISSING, target="https://example.co.uk/mp1", sources=[]),
        make_gap(keyword="schema", gap_type=GapType.SCHEMA_MISSING, target="https://example.co.uk/mp2", sources=[]),
        make_gap(keyword="schema", gap_type=GapType.SCHEMA_MISSING, target="https://example.co.uk/mp3", sources=[]),
        make_gap(keyword="schema", gap_type=GapType.SCHEMA_MISSING, target="https://example.co.uk/mp4", sources=[]),
        make_gap(keyword="mortgage advice leeds", gap_type=GapType.LOCAL_MISSING,
                 target="/leeds-mortgage-advice", sources=["cities"]),
        make_gap(keyword="zero evidence topic", gap_type=GapType.NO_PAGE,
                 target="/zero-evidence-topic", evidence={}, sources=["suggest"]),
    ]


_PHASE2_MONEY = ["capital one card", "capital one card rates", "beta capital card"]
_PHASE2_MONEY_URLS = ["https://example.co.uk/mp1", "https://example.co.uk/mp2"]


def test_shuffled_gaps_produce_identical_backlog_bytes():
    import random

    base = _phase2_gaps()
    money = list(_PHASE2_MONEY)
    expected = [
        item.model_dump_json()
        for item in build_backlog(
            list(base), money_keywords=money, money_urls=_PHASE2_MONEY_URLS
        )
    ]
    assert len(expected) > 0
    for seed in range(20):
        shuffled = list(base)
        random.Random(seed).shuffle(shuffled)  # noqa: S311 - determinism probe, not crypto
        actual = [
            item.model_dump_json()
            for item in build_backlog(
                shuffled, money_keywords=money, money_urls=_PHASE2_MONEY_URLS
            )
        ]
        assert actual == expected, f"seed {seed} produced a different backlog"


def test_money_tie_breaks_on_money_kw_count_before_target():
    gaps = [
        make_gap(keyword="beta capital card", target="/alpha-capital-card",
                 evidence={"cluster_keywords": ["beta capital card"]},
                 sources=["suggest"]),
        make_gap(keyword="capital one card", target="/zulu-capital-card",
                 evidence={"cluster_keywords": ["capital one card", "capital one card rates"]},
                 sources=["suggest"]),
    ]
    items = build_backlog(gaps, money_keywords=_PHASE2_MONEY)
    assert [item.target for item in items] == ["/zulu-capital-card", "/alpha-capital-card"]


def test_money_gsc_tie_keeps_equal_money_kw_count_and_orders_by_impressions():
    gaps = [
        make_gap(keyword="bad credit mortgage", target="/bad-credit-mortgage",
                 evidence={"gsc": {"impressions": 2.0}}, sources=["suggest"]),
        make_gap(keyword="remortgage calculator", target="/remortgage-calculator",
                 evidence={"gsc": {"impressions": 9.0}}, sources=["suggest"]),
    ]
    money = ["bad credit mortgage", "remortgage calculator"]
    items = build_backlog(gaps, money_keywords=money)
    assert [item.target for item in items] == ["/remortgage-calculator", "/bad-credit-mortgage"]
    assert [item.priority for item in items] == [0.5, 0.5]


def test_final_tie_breaks_by_gap_type_then_content():
    no_page = make_gap(keyword="rival topic", target="/rival-topic", sources=["suggest"])
    comp_covers = make_gap(
        keyword="rival topic", target="/rival-topic",
        sources=["habito.com"], gap_type=GapType.COMP_COVERS,
    )
    forward = [item.model_dump_json() for item in build_backlog([no_page, comp_covers])]
    backward = [item.model_dump_json() for item in build_backlog([comp_covers, no_page])]
    assert forward == backward
    items = build_backlog([no_page, comp_covers])
    assert [item.gap_type for item in items] == ["COMP_COVERS", "NO_PAGE"]
    assert [item.item_id for item in items] == ["BL-0001", "BL-0002"]
