"""JSON-LD templates: valid, deterministic and free of invented facts."""

from __future__ import annotations

import json

import pytest
from conftest import make_profile

from src.schema_gen import (
    SchemaError,
    breadcrumb_list,
    faq_page,
    financial_service,
    generate,
    schema_types,
    to_json,
    validate_schema,
)

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# FinancialService / LocalBusiness
# ---------------------------------------------------------------------------


def test_financial_service_uses_only_profile_fields():
    profile = make_profile()
    schema = financial_service(profile)
    assert schema["@context"] == "https://schema.org"
    assert schema["@type"] == "FinancialService"
    assert schema["url"] == "https://clearpath-mortgage.co.uk"
    assert schema["areaServed"] == [
        {"@type": "City", "name": "London"},
        {"@type": "City", "name": "Manchester"},
    ]
    assert schema["identifier"]["value"] == "123456"
    validate_schema(schema)


def test_local_business_variant():
    schema = financial_service(make_profile(), kind="LocalBusiness")
    assert schema["@type"] == "LocalBusiness"
    validate_schema(schema)


@pytest.mark.parametrize(
    "invented",
    ["aggregateRating", "review", "priceRange", "telephone", "address", "award"],
)
def test_financial_service_never_invents_facts(invented):
    schema = financial_service(make_profile())
    assert invented not in schema


def test_validate_rejects_invented_rating():
    schema = financial_service(make_profile())
    schema["aggregateRating"] = {"ratingValue": 5}
    with pytest.raises(SchemaError, match="must not invent"):
        validate_schema(schema)


def test_validate_rejects_missing_context_or_type():
    with pytest.raises(SchemaError, match="@context"):
        validate_schema({"@type": "FinancialService", "url": "https://x.co.uk"})
    with pytest.raises(SchemaError, match="@type"):
        validate_schema({"@context": "https://schema.org"})


def test_validate_rejects_missing_required_key():
    with pytest.raises(SchemaError, match="url"):
        validate_schema({"@context": "https://schema.org", "@type": "FinancialService"})


# ---------------------------------------------------------------------------
# FAQPage
# ---------------------------------------------------------------------------


def test_faq_page_builds_questions_and_answers():
    schema = faq_page(
        [
            ("Do you charge a fee?", "We do not charge a fee for our initial consultation."),
            {"q": "How long does it take?", "a": "Usually two to three weeks."},
        ]
    )
    assert schema["@type"] == "FAQPage"
    assert len(schema["mainEntity"]) == 2
    assert schema["mainEntity"][0]["acceptedAnswer"]["text"].startswith("We do not")
    validate_schema(schema)


def test_faq_page_rejects_empty_list():
    with pytest.raises(SchemaError, match="at least one"):
        faq_page([])


@pytest.mark.parametrize("item", [("", "answer"), ("question", ""), {"question": "q"}])
def test_faq_page_rejects_incomplete_entries(item):
    with pytest.raises(SchemaError):
        faq_page([item])


def test_faq_page_cleans_whitespace():
    schema = faq_page([("  What   is a mortgage? ", " A   loan secured on property. ")])
    assert schema["mainEntity"][0]["name"] == "What is a mortgage?"
    assert schema["mainEntity"][0]["acceptedAnswer"]["text"] == "A loan secured on property."


# ---------------------------------------------------------------------------
# BreadcrumbList
# ---------------------------------------------------------------------------


def test_breadcrumb_positions_are_one_based_and_urls_absolute():
    schema = breadcrumb_list(
        make_profile(),
        [("/", "Home"), ("/remortgage", "Remortgage"), ("/remortgage/calculator", "Calculator")],
    )
    elements = schema["itemListElement"]
    assert [item["position"] for item in elements] == [1, 2, 3]
    assert elements[0]["item"] == "https://clearpath-mortgage.co.uk/"
    assert elements[1]["item"] == "https://clearpath-mortgage.co.uk/remortgage"
    validate_schema(schema)


def test_breadcrumb_accepts_absolute_urls():
    schema = breadcrumb_list(make_profile(), [("https://example.com/x", "External")])
    assert schema["itemListElement"][0]["item"] == "https://example.com/x"


def test_breadcrumb_rejects_relative_non_root_paths():
    with pytest.raises(SchemaError, match="must start"):
        breadcrumb_list(make_profile(), [("remortgage", "Remortgage")])


def test_breadcrumb_rejects_empty_list():
    with pytest.raises(SchemaError, match="at least one"):
        breadcrumb_list(make_profile(), [])


# ---------------------------------------------------------------------------
# generate / serialisation
# ---------------------------------------------------------------------------


def test_generate_dispatches_supported_kinds():
    profile = make_profile()
    assert generate(profile)["@type"] == "FinancialService"
    assert generate(profile, "LocalBusiness")["@type"] == "LocalBusiness"
    assert generate(profile, "FAQPage", faqs=[("Q", "A")])["@type"] == "FAQPage"
    assert generate(profile, "BreadcrumbList", crumbs=[("/", "Home")])["@type"] == "BreadcrumbList"


def test_generate_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unsupported schema kind"):
        generate(make_profile(), "AggregateRating")


def test_to_json_is_sorted_and_stable():
    schema = financial_service(make_profile())
    first = to_json(schema)
    second = to_json(schema)
    assert first == second
    assert json.loads(first) == validate_schema(schema)
    assert first.index('"@context"') < first.index('"@type"')


def test_schema_types_constant_lists_supported_kinds():
    assert schema_types() == (
        "FinancialService",
        "LocalBusiness",
        "FAQPage",
        "BreadcrumbList",
    )
