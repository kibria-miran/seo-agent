"""Keyword normalisation, stemming, coverage, intent and clustering."""

from __future__ import annotations

import pytest

from conftest import make_keyword, make_page
from src import config
from src.keywords import (
    city_in,
    cluster,
    cluster_covered,
    head_covered,
    head_terms,
    intent_for,
    jaccard,
    normalise,
    page_covers,
    stem_token,
)

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# Normalisation / stemming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Free   Mortgage Advice! ", "free mortgage advice"),
        ("Re-mortgage", "remortgage"),
        ("re mortgage", "remortgage"),
        ("Remortgaging", "remortgaging"),
        ("ＭＯＲＴＧＡＧＥ", "mortgage"),
        ("buy-to-let", "buy to let"),
    ],
)
def test_normalise(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("remortgage", "remortgage"),
        ("remortgages", "remortgage"),
        ("advisors", "adviser"),
        ("fees", "fee"),
        ("mortgage", "mortgage"),
    ],
)
def test_stem_token(raw, expected):
    assert stem_token(raw) == expected


def test_head_terms_remove_the_uk_stoplist():
    assert head_terms("remortgage advice for first time buyers") == {
        "remortgage",
        "advice",
        "first",
        "time",
        "buyer",
    }


def test_head_covered_handles_re_mortgage_spelling():
    assert head_covered("remortgage advice", "Re-mortgage advice in Leeds")
    assert not head_covered("remortgage calculator", "Remortgage advice")


def test_head_covered_requires_every_significant_token():
    assert not head_covered("bad credit mortgage", "Bad mortgage advice")
    assert head_covered("bad credit mortgage", "Bad credit mortgage help")


def test_page_coverage_uses_title_or_h1_only():
    page = make_page(
        title="Remortgage Advice",
        h1_tags=["Something else"],
        meta_description="bad credit mortgage",
    )
    assert page_covers("remortgage advice", page)
    assert not page_covers("bad credit mortgage", page)


def test_cluster_covered_is_any_page():
    from conftest import make_cluster

    cluster_model = make_cluster(head_term="free mortgage advice")
    pages = [make_page(title="Home"), make_page(title="Free mortgage advice")]
    assert cluster_covered(cluster_model, pages)


# ---------------------------------------------------------------------------
# Intent and city
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("keyword", "expected"),
    [
        ("mortgage broker near me", "local"),
        ("mortgage advice manchester", "local"),
        ("remortgage calculator", "informational"),
        ("how much can i borrow", "informational"),
        ("apply for a mortgage", "transactional"),
        ("mortgage quote", "transactional"),
        ("mortgage adviser", "transactional"),
        ("buy to let mortgage", "informational"),
    ],
)
def test_intent_rules(keyword, expected):
    assert intent_for(keyword) == expected


def test_city_in_is_case_insensitive_and_canonical():
    assert city_in("mortgage advice MANCHESTER") == "Manchester"
    assert city_in("mortgage advice newcastle upon tyne") == "Newcastle upon Tyne"
    assert city_in("free mortgage advice") is None


def test_city_in_respects_a_restricted_city_list():
    assert city_in("mortgage advice manchester", ("London",)) is None
    assert city_in("mortgage advice london", ("London",)) == "London"


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def test_jaccard_is_symmetric_and_handles_empty():
    assert jaccard("free mortgage advice", "free mortgage advice uk") == 0.75
    assert jaccard("a", "") == 0.0
    assert jaccard("a", "a") == 1.0


def test_cluster_merges_near_duplicates_and_picks_shortest_head():
    clusters = cluster(
        [
            make_keyword(keyword="free mortgage advice uk"),
            make_keyword(keyword="free mortgage advice"),
            make_keyword(keyword="remortgage calculator"),
        ]
    )
    assert len(clusters) == 2
    merged = next(item for item in clusters if "free mortgage advice" in item.keywords)
    assert merged.head_term == "free mortgage advice"
    assert merged.keywords == ["free mortgage advice", "free mortgage advice uk"]


def test_cluster_does_not_merge_merely_shared_mortgage():
    clusters = cluster(
        [
            make_keyword(keyword="bad credit mortgage"),
            make_keyword(keyword="buy to let mortgage"),
        ]
    )
    assert len(clusters) == 2


def test_cluster_is_order_independent_and_ids_are_stable():
    values = ["zebra mortgage", "alpha mortgage", "alpha mortgage uk"]
    first = [item.model_dump_json() for item in cluster(values)]
    second = [item.model_dump_json() for item in cluster(list(reversed(values)))]
    assert first == second
    ids = [item.cluster_id for item in cluster(values)]
    assert ids == [f"c{index:02d}" for index in range(1, len(ids) + 1)]


def test_cluster_threshold_can_be_raised():
    values = ["free mortgage advice", "free mortgage advice uk"]
    assert len(cluster(values, threshold=0.9)) == 2


def test_cluster_empty_returns_empty():
    assert cluster([]) == []


def test_cluster_default_threshold_comes_from_config():
    assert config.JACCARD_THRESHOLD == 0.6
