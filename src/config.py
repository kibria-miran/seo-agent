"""Central configuration.

Everything that a test, budget check or compliance rule needs to know lives
here. Modules must not hard-code caps, city lists, disclosure phrases or
weights; they import them from this file.

No timestamps are created here. Use ``src.clock.now()`` for time.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from urllib.parse import urlsplit

try:  # optional, the app works without a .env
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001, S110 - dotenv is an optional convenience
    pass


# Point SEO_AGENT_ROOT at a checkout when the package is installed outside the
# repo (pip install .): paths for profiles/, third_party/, out/ and logs/ all
# derive from it. Default stays the repository root.
ROOT = (
    Path(os.environ["SEO_AGENT_ROOT"]).expanduser().resolve()
    if os.environ.get("SEO_AGENT_ROOT")
    else Path(__file__).resolve().parent.parent
)

# Read-only data (vendored audit layer, profiles, evals) ships both in the
# checkout (ROOT-relative) and, for wheel installs, bundled under src/resources.
# Resolve to the checkout copy when present, otherwise the bundled copy, so the
# package is self-contained after ``pip install`` while tests keep running
# against the live checkout.
_BUNDLED = Path(__file__).resolve().parent / "resources"


def _locate(*rel: str) -> Path:
    """Return an existing path for read-only data: checkout first, then bundled.

    The checkout copy wins when running from the source tree (tests, dev).
    After ``pip install`` the checkout siblings do not exist, so the wheel's
    bundled copy under ``src/resources`` is used. Never used for writable
    output (OUT_DIR / LOGS_DIR / DATA_DIR / CACHE_DIR stay ROOT-relative).
    """
    checkout = ROOT.joinpath(*rel)
    if checkout.exists():
        return checkout
    return _BUNDLED.joinpath(*rel)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

APP_NAME = "seo-agent"
APP_VERSION = "0.1.0"
CONTACT_EMAIL = os.getenv("SEO_AGENT_CONTACT", "seo-agent@example.co.uk")
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (+contact: {CONTACT_EMAIL})"

# Optional headless-Chrome crawl for hosts that answer plain HTTP with a
# JavaScript bot-challenge or render content client-side. Off by default:
# it is slower and needs Chrome installed.
RENDER_JS = os.getenv("SEO_AGENT_RENDER", "").strip().lower() in {"1", "true", "yes", "on"}

# Placeholder demo values shipped in profiles/site.json. Live runs against
# these are refused unless the operator explicitly acknowledges the demo
# profile (SEO_AGENT_ALLOW_DEMO_PROFILE=1) or passes --fixture.
PLACEHOLDER_DOMAIN = "https://clearpath-mortgage.co.uk"
PLACEHOLDER_FCA_REF = "123456"
ALLOW_DEMO_PROFILE_ENV = "SEO_AGENT_ALLOW_DEMO_PROFILE"

# ---------------------------------------------------------------------------
# Vendored audit layer (D-1)
# ---------------------------------------------------------------------------

SEOEXTRACT_COMMIT = "6544a74e340e6ac8b147b7f4ab0f09d55d142dd3"
SEOEXTRACT_VERSION = "0.3.0"
SEOEXTRACT_DIR = _locate("third_party", "seoextract")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OUT_DIR = ROOT / "out"
# D-15 allows writes only under out/ and logs/. App state and the future source
# cache therefore live inside out/, not in sibling top-level directories.
DATA_DIR = OUT_DIR / "state"
CACHE_DIR = OUT_DIR / "cache"
LOGS_DIR = ROOT / "logs"
PROFILES_DIR = _locate("profiles")
EVALS_DIR = _locate("evals")
FIXTURES_DIR = _locate("tests", "fixtures")
SCENARIOS_DIR = EVALS_DIR / "scenarios"
EXTRA_SCENARIOS_DIR = EVALS_DIR / "extra"
RESULTS_DIR = EVALS_DIR / "results"

DB_PATH = DATA_DIR / "seo.db"
TRACE_PATH = LOGS_DIR / "trace.jsonl"
BANNED_CLAIMS_PATH = EVALS_DIR / "banned_claims.json"
INJECTION_PAYLOADS_PATH = EVALS_DIR / "injection_payloads.json"
BASELINES_PATH = EVALS_DIR / "baselines.json"

# ---------------------------------------------------------------------------
# Budgets (D-13). Enforced in code, never by prompts.
# ---------------------------------------------------------------------------

MAX_STEPS = 12
MAX_LLM_CALLS = 20
MAX_TOKENS_IN = 20_000
MAX_TOKENS_OUT = 5_000
MAX_LLM_SECONDS = 180
MAX_FETCHES = 120
MAX_RUN_SECONDS = 600

# ---------------------------------------------------------------------------
# Crawl / source limits (D-5)
# ---------------------------------------------------------------------------

MAX_OWN_PAGES = 50
MAX_COMP_PAGES = 5
MAX_SUGGEST = 400
MAX_SERP_QUERIES = 25
MAX_BACKLOG = 30

HOST_DELAY_SECONDS = 2.0
CACHE_TTL_SECONDS = 86_400
HTTP_TIMEOUT_SECONDS = 10.0
SLOW_PAGE_MS = 2_000

# Kept explicit so tests can prove HEAD is not counted and GET is.
COUNT_HEAD_AGAINST_FETCH_BUDGET = False

# ---------------------------------------------------------------------------
# LLM (NVIDIA NIM chat API; keyless features stay usable without it)
# ---------------------------------------------------------------------------

NIM_BASE_URL = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_MODEL = os.getenv("NIM_MODEL", "mistralai/mistral-large-4-1t-a52b")
NIM_API_KEY_ENV = "NVIDIA_API_KEY"
LLM_TIMEOUT_SECONDS = 30.0
LLM_TEMPERATURE = 0.3

# ---------------------------------------------------------------------------
# UK cities. SiteProfile.cities must be a case-insensitive subset.
# ---------------------------------------------------------------------------

UK_CITIES: tuple[str, ...] = (
    "London",
    "Birmingham",
    "Manchester",
    "Leeds",
    "Liverpool",
    "Sheffield",
    "Bristol",
    "Newcastle upon Tyne",
    "Nottingham",
    "Leicester",
    "Coventry",
    "Bradford",
    "Cardiff",
    "Belfast",
    "Edinburgh",
    "Glasgow",
    "Aberdeen",
    "Dundee",
    "Swansea",
    "Newport",
    "Southampton",
    "Portsmouth",
    "Brighton",
    "Plymouth",
    "Reading",
    "Oxford",
    "Cambridge",
    "Milton Keynes",
    "Norwich",
    "Derby",
    "Stoke-on-Trent",
    "Wolverhampton",
    "Sunderland",
    "York",
    "Bath",
    "Exeter",
    "Lincoln",
    "Chester",
    "Durham",
    "Inverness",
)

CITY_LOOKUP = {c.casefold(): c for c in UK_CITIES}

# ---------------------------------------------------------------------------
# Intent rules (section 7). Order matters: the first matching rule wins.
# ---------------------------------------------------------------------------

TRANSACTIONAL_TOKENS = (
    "near me",
    "broker",
    "adviser",
    "advisor",
    "apply",
    "quote",
)
INFORMATIONAL_TOKENS = (
    "how",
    "what",
    "can i",
    "calculator",
    "guide",
    "cost",
    "fees",
)
LOCAL_NEAR_ME = "near me"

# ---------------------------------------------------------------------------
# Keywords / coverage (I-9)
# ---------------------------------------------------------------------------

JACCARD_THRESHOLD = 0.6
# Generic tokens that carry no coverage signal. "remortgage" is deliberately
# NOT here: it is often the head term we must match in a title or H1.
UK_MORTGAGE_STOPLIST = frozenset(
    {
        "mortgage",
        "the",
        "a",
        "an",
        "uk",
        "for",
        "in",
        "with",
        "and",
        "of",
        "to",
        "on",
        "is",
        "are",
        "near",
        "me",
        "how",
        "what",
        "can",
        "i",
        "my",
        "your",
        "best",
    }
)
# N-15: the N-5 NO_PAGE pre-check matches prose (title/H1/H2), not slugs, so
# the slug stoplist is too aggressive there: `mortgage` is the head term most
# keywords share and must stay significant. Pre-check use only; slug
# tokenisation is untouched.
PRECHECK_STOPLIST = UK_MORTGAGE_STOPLIST - {"mortgage"}

# ---------------------------------------------------------------------------
# Scoring (section 7)
# ---------------------------------------------------------------------------

IMPACT_CRITICAL = 3
IMPACT_WARNING = 2
IMPACT_INFO = 1

CONFIDENCE_AUDIT = 1.0
CONFIDENCE_MULTI_SOURCE = 0.8
CONFIDENCE_DUAL_SOURCE = 0.65
CONFIDENCE_SINGLE_SOURCE = 0.5

EFFORT_META = 1
EFFORT_SCHEMA = 2
EFFORT_PAGE = 3

MULTI_SOURCE_THRESHOLD = 3

# WEAK_PAGE candidates must share at least this many significant slug
# tokens with the cluster head term (capped by the head term's size).
WEAK_PAGE_MIN_SLUG_OVERLAP = 2

# GSC demand weighting for backlog priority: impressions observed for a
# cluster's queries scale the priority of gaps tied to that cluster.
GSC_BOOST_TIER_1_IMPRESSIONS = 1000
GSC_BOOST_TIER_2_IMPRESSIONS = 100
GSC_BOOST_TIER_3_IMPRESSIONS = 10
GSC_BOOST_TIER_1 = 1.5
GSC_BOOST_TIER_2 = 1.25
GSC_BOOST_TIER_3 = 1.1

# More than this many SCHEMA_MISSING findings are grouped into one umbrella
# backlog item; the per-page gaps remain in the report's gap list.
SCHEMA_UMBRELLA_MIN_PAGES = 3
SCHEMA_UMBRELLA_MAX_EFFORT = 8

# Option A: the LLM explains WHY the top backlog items matter and WHAT to do.
# It never sets priority, rank, effort or compliance (D-2) — those stay in code.
ANALYSIS_LIMIT = 5
ANALYSIS_MAX_TOKENS = 900
ANALYSIS_MAX_CHARS = 400

# ---------------------------------------------------------------------------
# Compliance (section 8.6 / 10). Starting point, not legal advice.
# ---------------------------------------------------------------------------

BANNED_CLAIMS: tuple[str, ...] = (
    "guaranteed approval",
    "guaranteed mortgage",
    "guaranteed accepted",
    "best rates",
    "lowest rates",
    "cheapest",
    "100% success",
    "risk-free",
    "no credit check",
)

# C1b: bare "no fees" only passes with one of these in the same draft.
FREE_DISCLOSURE_PHRASES: tuple[str, ...] = (
    "we do not charge a fee for our initial consultation",
    "we don't charge a fee for our initial consultation",
    "no fees are payable by you",
    "there is no fee for the initial consultation",
    "free initial consultation",
    "we may charge a fee",
    "a fee may be payable",
)

RISK_WARNING = (
    "your home may be repossessed if you do not keep up repayments on your mortgage"
)

REPRESENTATIVE_EXAMPLE = "representative example"

# C6: invented social proof / partnerships. Matched case-insensitively.
BANNED_SOCIAL_PROOF_PATTERNS: tuple[str, ...] = (
    r"\b5[\s-]?star\b",
    r"\bfive[\s-]?star\b",
    r"\b\d(?:\.\d)?[\s-]?star\b",
    r"\baward[\s-]?winning\b",
    r"\btrusted by\b",
    r"\bpartnered with\b",
    r"\bofficial partner\b",
    r"\bapproved by\s+(?!the\s+fca|fca\b)[a-z]",
    r"\btestimonial",
    r"\bverified reviews?\b",
    r"\bnumber one broker\b",
    r"\b#1 broker\b",
)

# C5: a rate or APR *figure* needs a representative example. A bare phrase such
# as "interest rates explained" is not a figure and must not be gated.
RATE_PATTERN = r"\b\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s*apr\b"

CONTENT_PAGE_KINDS = frozenset({"content", "page", "mortgage", "brief", "draft", "faq"})

# ---------------------------------------------------------------------------
# Injection filter (10.1 / I-5)
# ---------------------------------------------------------------------------

INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous",
    "ignore all previous",
    "disregard",
    "system prompt",
    "you are now",
    "new instructions",
    "reveal your",
)

# ---------------------------------------------------------------------------
# Deterministic report / scoring helpers
# ---------------------------------------------------------------------------

GRADE_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (90.0, "A"),
    (75.0, "B"),
    (60.0, "C"),
    (40.0, "D"),
    (0.0, "F"),
)


def normalize_domain(value: str | None) -> str:
    """Return the domain key for a site url or host: lowercase host,
    leading ``www.`` stripped, port stripped. Empty string when unparseable."""
    raw = (value or "").strip().casefold()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError:
        return ""
    host = host.casefold().removeprefix("www.")
    return host


def grade_for(score: float) -> str:
    """Return the deterministic letter grade for a site score."""

    for threshold, letter in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"


def canonical_city(value: str) -> str | None:
    """Return the canonical UK city spelling, or None if not a served city."""

    return CITY_LOOKUP.get(value.strip().casefold())


def _warn_com_domain(domain: str) -> None:
    warnings.warn(
        f"{domain!r} uses a .com host; the UK mortgage profile expects .co.uk or .uk",
        UserWarning,
        stacklevel=3,
    )


__all__ = [name for name in dir() if name.isupper()] + [
    "grade_for",
    "canonical_city",
    "normalize_domain",
]
