"""Backlog scoring, tie-breaks, determinism and caps (section 8.4)."""

from __future__ import annotations

import pytest

from src import config
from src.backlog import (
    build_backlog,
    confidence_for,
    effort_for,
    impact_for,
    priority_for,
)
from src.models import GapType
from conftest import make_gap

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
