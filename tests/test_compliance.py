"""Compliance gate tests: one pass and one fail per rule.

Rule IDs appear in the test names so a failing test names the rule it defends.
This is a starting point, not legal advice (section 8.6).
"""

from __future__ import annotations

import pytest

from src import config
from src.compliance import Violation, check_many, check_text

pytestmark = pytest.mark.fast


def rules(violations: list[Violation]) -> set[str]:
    return {violation.rule for violation in violations}


def mortgage_body(extra: str = "") -> str:
    """A content draft that satisfies C3 and C4 so other rules can be isolated."""

    return f"FCA firm reference 123456. {config.RISK_WARNING}. {extra}"


# ---------------------------------------------------------------------------
# C1 -- banned absolutes, negation-aware
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "guaranteed approval",
        "we offer guaranteed mortgage approval",
        "the best rates in the uk",
        "cheapest broker in leeds",
        "100% success",
        "market-leading rates",  # loaded from evals/banned_claims.json
    ],
)
def test_C1_fails_on_banned_absolute(claim):
    ok, violations = check_text(claim, "meta")
    assert not ok
    assert "C1" in rules(violations)


@pytest.mark.parametrize(
    "text",
    [
        "this is not guaranteed approval",
        "we are not the cheapest broker",
        "we never promise the best rates",
        "we compare options from across the market",
    ],
)
def test_C1_permits_negated_or_ordinary_copy(text):
    ok, violations = check_text(text, "meta")
    assert ok, [str(v) for v in violations]
    assert "C1" not in rules(violations)


def test_C1_does_not_confuse_bare_no_fees_with_an_absolute():
    ok, violations = check_text("no fees", "meta")
    assert not ok  # C1b fires
    assert "C1" not in rules(violations)


def test_C1_sees_through_zero_width_obfuscation():
    ok, violations = check_text("guar\u200banteed approval", "meta")
    assert not ok
    assert "C1" in rules(violations)


# ---------------------------------------------------------------------------
# C1b -- bare "no fees" needs a disclosure sentence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["no fees", "No fee. Speak to us today.", "there are no fees"])
def test_C1b_fails_without_disclosure(text):
    ok, violations = check_text(text, "meta")
    assert not ok
    assert "C1b" in rules(violations)


def test_C1b_passes_when_no_fees_is_itself_a_disclosure():
    ok, violations = check_text("No fees are payable by you.", "meta")
    assert ok, [str(v) for v in violations]


def test_C1b_passes_with_a_separate_disclosure_sentence():
    text = "No fees. We do not charge a fee for our initial consultation."
    ok, violations = check_text(text, "meta")
    assert ok, [str(v) for v in violations]


# ---------------------------------------------------------------------------
# C2 -- "free" needs a disclosure sentence
# ---------------------------------------------------------------------------


def test_C2_fails_on_free_without_disclosure():
    ok, violations = check_text("Free mortgage advice", "meta")
    assert not ok
    assert "C2" in rules(violations)


def test_C2_passes_when_free_is_part_of_the_disclosure():
    ok, violations = check_text("Free initial consultation", "meta")
    assert ok, [str(v) for v in violations]


def test_C2_passes_with_a_separate_disclosure():
    text = "Free mortgage advice. We do not charge a fee for our initial consultation."
    ok, violations = check_text(text, "meta")
    assert ok, [str(v) for v in violations]


def test_C2_ignores_freehold():
    ok, violations = check_text("Freehold property finance", "meta")
    assert ok, [str(v) for v in violations]
    assert "C2" not in rules(violations)


def test_C2_accepts_a_curly_apostrophe_disclosure():
    text = "Free mortgage advice. We don\u2019t charge a fee for our initial consultation."
    ok, violations = check_text(text, "meta")
    assert ok, [str(v) for v in violations]


def test_check_many_shares_disclosure_context_across_fields():
    ok, violations = check_many(
        ["Free mortgage advice", "We do not charge a fee for our initial consultation."],
        "meta",
    )
    assert ok, [str(v) for v in violations]


# ---------------------------------------------------------------------------
# C3 -- repossession risk warning
# ---------------------------------------------------------------------------


def test_C3_fails_on_mortgage_content_without_risk_warning():
    ok, violations = check_text("FCA firm reference 123456. Compare remortgage deals.", "content")
    assert not ok
    assert "C3" in rules(violations)


def test_C3_passes_with_risk_warning():
    ok, violations = check_text(mortgage_body("Compare remortgage deals."), "content")
    assert ok, [str(v) for v in violations]


def test_C3_is_not_required_in_a_title_or_meta():
    ok, violations = check_text("Remortgage advice | ClearPath", "title")
    assert ok, [str(v) for v in violations]
    assert "C3" not in rules(violations)


# ---------------------------------------------------------------------------
# C4 -- FCA firm reference
# ---------------------------------------------------------------------------


def test_C4_fails_without_a_firm_reference():
    text = f"{config.RISK_WARNING}. Compare remortgage deals."
    ok, violations = check_text(text, "content")
    assert not ok
    assert "C4" in rules(violations)


def test_C4_passes_with_an_explicit_reference():
    text = f"{config.RISK_WARNING}. Compare remortgage deals."
    ok, violations = check_text(text, "content", fca_firm_ref="123456")
    assert not ok  # ref is not in the text
    assert "C4" in rules(violations)

    ok, violations = check_text(text + " FCA 123456", "content", fca_firm_ref="123456")
    assert ok, [str(v) for v in violations]


def test_C4_accepts_firm_reference_wording_without_an_explicit_argument():
    text = mortgage_body("Compare remortgage deals.")
    ok, violations = check_text(text, "content")
    assert ok, [str(v) for v in violations]


def test_C4_is_not_required_in_a_title():
    ok, violations = check_text("Remortgage advice | ClearPath", "title")
    assert ok, [str(v) for v in violations]


# ---------------------------------------------------------------------------
# C5 -- rate/APR figure needs a representative example
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    ["Rates from 4.5% APR.", "A 3.9% fixed rate for two years.", "APR 5.2% variable."],
)
def test_C5_fails_on_rate_figure_without_representative_example(claim):
    ok, violations = check_text(mortgage_body(claim), "content")
    assert not ok
    assert "C5" in rules(violations)


def test_C5_passes_with_representative_example():
    text = mortgage_body(
        "Rates from 4.5% APR. Representative example: a 4.5% APR fixed rate over 25 years."
    )
    ok, violations = check_text(text, "content")
    assert ok, [str(v) for v in violations]


def test_C5_does_not_fire_on_the_words_interest_rates_alone():
    text = mortgage_body("Interest rates explained in plain English.")
    ok, violations = check_text(text, "content")
    assert ok, [str(v) for v in violations]
    assert "C5" not in rules(violations)


# ---------------------------------------------------------------------------
# C6 -- invented social proof / partnerships
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "Rated 5-star by our customers.",
        "An award-winning mortgage broker.",
        "Trusted by 10,000 homeowners.",
        "Partnered with Barclays.",
        "Read our testimonials.",
    ],
)
def test_C6_fails_on_invented_social_proof(claim):
    ok, violations = check_text(claim, "meta")
    assert not ok
    assert "C6" in rules(violations)


def test_C6_permits_regulatory_approval_wording():
    ok, violations = check_text("Approved by the FCA. Firm reference 123456.", "meta")
    assert "C6" not in rules(violations)


def test_C6_permits_negated_social_proof():
    ok, violations = check_text("We do not use testimonials.", "meta")
    assert "C6" not in rules(violations)


# ---------------------------------------------------------------------------
# Whole-draft gate (S16)
# ---------------------------------------------------------------------------


def test_S16_fully_compliant_draft_passes_C1_to_C6():
    draft = (
        "Free initial consultation. No fees are payable by you. "
        "We compare remortgage options from across the market. "
        f"{config.RISK_WARNING}. "
        "Representative example: a 4.2% APR fixed rate over 25 years. "
        "FCA firm reference 123456."
    )
    ok, violations = check_text(draft, "content", fca_firm_ref="123456")
    assert ok, [str(v) for v in violations]
    assert rules(violations) == set()


def test_violations_are_str_friendly_for_logs():
    ok, violations = check_text("guaranteed approval", "meta")
    assert not ok
    rendered = [str(v) for v in violations]
    assert any("C1" in item for item in rendered)
