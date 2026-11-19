"""Config constants, profile validators and the vendored pin.

These tests are deliberately about invariants, not implementation details:
budget names from D-13, city/domain/FCA validation from I-18, and the exact
vendored commit from D-1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_profile
from pydantic import ValidationError

from src import clock, config
from src.models import SiteProfile

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# D-13 budgets
# ---------------------------------------------------------------------------


def test_d13_budget_constants_are_exact():
    assert config.MAX_STEPS == 12
    assert config.MAX_LLM_CALLS == 20
    assert config.MAX_TOKENS_IN == 20_000
    assert config.MAX_TOKENS_OUT == 5_000
    assert config.MAX_LLM_SECONDS == 180
    assert config.MAX_FETCHES == 120
    assert config.MAX_RUN_SECONDS == 600


def test_d13_budget_relationships_are_sane():
    assert config.MAX_LLM_SECONDS < config.MAX_RUN_SECONDS
    assert config.MAX_TOKENS_OUT < config.MAX_TOKENS_IN
    assert config.MAX_LLM_CALLS <= config.MAX_STEPS * 2
    assert config.MAX_FETCHES > config.MAX_COMP_PAGES
    assert config.MAX_BACKLOG == 30


def test_d5_politeness_and_cache_constants():
    assert config.HOST_DELAY_SECONDS >= 2.0
    assert config.CACHE_TTL_SECONDS == 86_400
    assert config.MAX_OWN_PAGES == 50
    assert config.MAX_COMP_PAGES == 5
    assert config.MAX_SUGGEST == 400
    assert config.MAX_SERP_QUERIES == 25


# ---------------------------------------------------------------------------
# I-1 vendored fork
# ---------------------------------------------------------------------------


def test_d1_seoextract_commit_is_pinned_and_documented():
    commit = config.SEOEXTRACT_COMMIT
    assert len(commit) == 40
    assert all(char in "0123456789abcdef" for char in commit)
    provenance = (config.ROOT / "third_party" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert commit in provenance
    assert "6544a74" in provenance


def test_d1_vendored_package_is_present():
    package = config.SEOEXTRACT_DIR / "seoextract" / "__init__.py"
    assert package.exists(), "vendor seoextract before running a live audit"
    assert "__version__" in package.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# I-18 SiteProfile validators
# ---------------------------------------------------------------------------


def test_profile_accepts_a_valid_uk_site():
    profile = make_profile()
    assert profile.base_url == "https://clearpath-mortgage.co.uk"
    assert profile.fca_firm_ref == "123456"
    assert profile.cities == ["London", "Manchester"]


def test_profile_reads_the_real_profiles_file():
    raw = json.loads((config.PROFILES_DIR / "site.json").read_text(encoding="utf-8"))
    profile = SiteProfile(**raw)
    assert profile.domain.startswith("https://")
    assert len(profile.target_keywords) >= 10
    assert profile.competitors
    assert len(profile.cities) == 8


@pytest.mark.parametrize(
    "domain",
    ["http://clearpath-mortgage.co.uk", "clearpath-mortgage.co.uk", "https://clearpath.org"],
)
def test_profile_rejects_non_https_or_non_uk_tld(domain):
    with pytest.raises(ValidationError):
        make_profile(domain=domain)


def test_profile_warns_for_com_domain_but_accepts_it():
    with pytest.warns(UserWarning, match=r"\.com"):
        profile = make_profile(domain="https://example.com")
    assert profile.domain == "https://example.com"


@pytest.mark.parametrize("ref", ["12345", "1234567", "12345a", ""])
def test_profile_rejects_bad_fca_reference(ref):
    with pytest.raises(ValidationError):
        make_profile(fca_firm_ref=ref)


@pytest.mark.parametrize("page", ["remortgage", "//remortgage", "https://x.co.uk/remortgage"])
def test_profile_requires_root_relative_money_pages(page):
    with pytest.raises(ValidationError):
        make_profile(money_pages=[page])


def test_profile_normalises_city_case_and_preserves_order():
    profile = make_profile(cities=["manchester", "LONDON"])
    assert profile.cities == ["Manchester", "London"]


def test_profile_rejects_unserved_city():
    with pytest.raises(ValidationError, match=r"not in config\.UK_CITIES"):
        make_profile(cities=["Atlantis"])


@pytest.mark.parametrize(
    "competitor",
    ["https://habito.com", "habito.com/path", "habito.com:443", "not a domain", "habito"],
)
def test_profile_rejects_bad_competitor_hosts(competitor):
    with pytest.raises(ValidationError):
        make_profile(competitors=[competitor])


def test_profile_rejects_duplicate_competitors_case_insensitively():
    with pytest.raises(ValidationError, match="duplicate"):
        make_profile(competitors=["habito.com", "HABITO.com"])


def test_profile_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        make_profile(typo_domain="https://example.co.uk")


# ---------------------------------------------------------------------------
# Deterministic helpers and other constants
# ---------------------------------------------------------------------------


def test_grade_thresholds_are_deterministic():
    assert config.grade_for(90) == "A"
    assert config.grade_for(89.9) == "B"
    assert config.grade_for(75) == "B"
    assert config.grade_for(74.9) == "C"
    assert config.grade_for(60) == "C"
    assert config.grade_for(59.9) == "D"
    assert config.grade_for(40) == "D"
    assert config.grade_for(39.9) == "F"
    assert config.grade_for(0) == "F"


def test_canonical_city_is_case_insensitive():
    assert config.canonical_city("london") == "London"
    assert config.canonical_city("NEWCASTLE UPON TYNE") == "Newcastle upon Tyne"
    assert config.canonical_city("Atlantis") is None


def test_clock_is_utc_and_aware():
    value = clock.now()
    assert value.tzinfo is not None
    assert value.utcoffset().total_seconds() == 0


def test_compliance_constants_cover_the_spec_rules():
    assert "guaranteed approval" in config.BANNED_CLAIMS
    assert "best rates" in config.BANNED_CLAIMS
    assert any("fee" in phrase for phrase in config.FREE_DISCLOSURE_PHRASES)
    assert "repossessed" in config.RISK_WARNING
    assert config.REPRESENTATIVE_EXAMPLE == "representative example"
    assert len(config.BANNED_SOCIAL_PROOF_PATTERNS) >= 4


def test_required_paths_are_under_the_project_root():
    for path in (config.DATA_DIR, config.CACHE_DIR, config.LOGS_DIR, config.OUT_DIR):
        assert Path(path).is_relative_to(config.ROOT)


def test_no_secret_is_stored_in_config():
    assert "NVIDIA_API_KEY" not in config.__dict__
    assert not any(
        value.startswith("nvapi-")
        for value in config.__dict__.values()
        if isinstance(value, str)
    )
