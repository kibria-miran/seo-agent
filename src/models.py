"""Pydantic models shared by every layer.

The models are deliberately strict about the things that affect correctness
(domain shape, FCA reference, cities, enum values) and tolerant about extra
metadata from upstream audit output, so a seoextract minor version cannot
cascade into the pipeline.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src import config

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class GapType(str, Enum):
    NO_PAGE = "NO_PAGE"
    WEAK_PAGE = "WEAK_PAGE"
    LOCAL_MISSING = "LOCAL_MISSING"
    SCHEMA_MISSING = "SCHEMA_MISSING"
    COMP_COVERS = "COMP_COVERS"


class Intent(str, Enum):
    TRANSACTIONAL = "transactional"
    INFORMATIONAL = "informational"
    LOCAL = "local"


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)
_FCA_RE = re.compile(r"^\d{6}$")


class SiteProfile(BaseModel):
    """The one hand-edited input file: ``profiles/site.json``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    domain: str
    money_pages: list[str]
    target_keywords: list[str]
    competitors: list[str]
    cities: list[str]
    fca_firm_ref: str

    @field_validator("domain")
    @classmethod
    def _validate_domain(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https":
            raise ValueError("domain must start with https://")
        if not parsed.hostname:
            raise ValueError("domain must include a host")
        host = parsed.hostname.lower()
        if host.endswith((".co.uk", ".uk")):
            return value.rstrip("/")
        if host.endswith(".com"):
            config._warn_com_domain(value)
            return value.rstrip("/")
        raise ValueError(
            "domain host must end in .co.uk, .uk or .com (got "
            f"{host!r}); .org/.io are not accepted"
        )

    @field_validator("fca_firm_ref")
    @classmethod
    def _validate_fca(cls, value: str) -> str:
        if not _FCA_RE.match(value):
            raise ValueError("fca_firm_ref must be exactly 6 digits")
        return value

    @field_validator("money_pages")
    @classmethod
    def _validate_money_pages(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("money_pages must not be empty")
        for page in value:
            if not page.startswith("/") or page.startswith("//"):
                raise ValueError(f"money page {page!r} must be root-relative ('/...')")
        return value

    @field_validator("target_keywords")
    @classmethod
    def _validate_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [kw.strip().lower() for kw in value if kw and kw.strip()]
        if not cleaned:
            raise ValueError("target_keywords must not be empty")
        # Stable de-duplication preserves the profile's intended order.
        return list(dict.fromkeys(cleaned))

    @field_validator("cities")
    @classmethod
    def _validate_cities(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("cities must not be empty")
        canonical: list[str] = []
        for city in value:
            match = config.canonical_city(city)
            if match is None:
                raise ValueError(
                    f"{city!r} is not in config.UK_CITIES; add it there first"
                )
            canonical.append(match)
        return list(dict.fromkeys(canonical))

    @field_validator("competitors")
    @classmethod
    def _validate_competitors(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("competitors must not be empty")
        seen: set[str] = set()
        cleaned: list[str] = []
        for raw in value:
            domain = raw.strip().lower()
            if "://" in domain:
                raise ValueError(f"competitor {raw!r} must not include a scheme")
            if "/" in domain or ":" in domain:
                raise ValueError(f"competitor {raw!r} must be a bare host")
            if not _HOST_RE.match(domain):
                raise ValueError(f"competitor {raw!r} is not a resolvable host")
            if domain in seen:
                raise ValueError(f"duplicate competitor {domain!r}")
            seen.add(domain)
            cleaned.append(domain)
        return cleaned

    @property
    def base_url(self) -> str:
        return self.domain.rstrip("/")

    @property
    def money_urls(self) -> list[str]:
        return [f"{self.base_url}{path}" for path in self.money_pages]


# ---------------------------------------------------------------------------
# Audit layer
# ---------------------------------------------------------------------------


class SEOIssue(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    page_url: str
    issue_type: str
    severity: Severity = Severity.INFO
    current_value: str = ""
    suggestion: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("issue_type", mode="before")
    @classmethod
    def _coerce_issue_type(cls, value: Any) -> Any:
        # seoextract uses an IssueType enum whose .value is the human label.
        return getattr(value, "value", value)


class PageData(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    url: str
    status_code: int = 200
    title: str | None = None
    meta_description: str | None = None
    h1_tags: list[str] = Field(default_factory=list)
    h2_tags: list[str] = Field(default_factory=list)
    h3_tags: list[str] = Field(default_factory=list)
    h1_count: int = 0
    h_tags: dict[str, list[str]] = Field(default_factory=dict)
    word_count: int = 0
    page_score: float = 0.0
    response_time_ms: float = 0.0
    schema_types: list[str] = Field(default_factory=list)
    issues: list[SEOIssue] = Field(default_factory=list)
    final_url: str | None = None

    @model_validator(mode="after")
    def _sync_headings(self) -> PageData:
        if self.h1_tags and not self.h1_count:
            self.h1_count = len(self.h1_tags)
        if not self.h_tags:
            self.h_tags = {
                "h1": list(self.h1_tags),
                "h2": list(self.h2_tags),
                "h3": list(self.h3_tags),
            }
        return self

    @property
    def meta_desc(self) -> str | None:
        """Spec/database spelling; kept as a read-only alias."""

        return self.meta_description

    @property
    def h1(self) -> str:
        return self.h1_tags[0] if self.h1_tags else ""


class AuditSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    site_score: float = 0.0
    grade: str = "F"
    pages_crawled: int = 0
    total_issues: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    pages: list[PageData] = Field(default_factory=list)
    issues: list[SEOIssue] = Field(default_factory=list)
    audit_date: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fill_counts(self) -> AuditSnapshot:
        if self.pages and not self.pages_crawled:
            self.pages_crawled = len(self.pages)
        if self.issues:
            if not self.total_issues:
                self.total_issues = len(self.issues)
            if not self.critical_count:
                self.critical_count = sum(
                    i.severity == Severity.CRITICAL for i in self.issues
                )
            if not self.warning_count:
                self.warning_count = sum(
                    i.severity == Severity.WARNING for i in self.issues
                )
            if not self.info_count:
                self.info_count = sum(i.severity == Severity.INFO for i in self.issues)
        if not self.grade:
            self.grade = config.grade_for(self.site_score)
        return self

    def page(self, url: str) -> PageData | None:
        for page in self.pages:
            if page.url == url:
                return page
        return None


# ---------------------------------------------------------------------------
# Demand data
# ---------------------------------------------------------------------------


class Keyword(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    keyword: str
    source: str = "suggest"
    cluster_id: str | None = None
    intent: Intent = Intent.INFORMATIONAL
    city: str | None = None
    gsc_clicks: float | None = None
    gsc_impressions: float | None = None
    gsc_ctr: float | None = None
    gsc_position: float | None = None

    @field_validator("keyword")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return " ".join(value.casefold().split())


class Cluster(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    cluster_id: str
    label: str = ""
    head_term: str = ""
    keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_head(self) -> Cluster:
        if not self.head_term and self.keywords:
            self.head_term = min(self.keywords, key=lambda k: (len(k), k))
        return self


class SerpResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str
    rank: int
    url: str
    title: str = ""
    snippet: str = ""
    domain: str = ""

    @model_validator(mode="after")
    def _fill_domain(self) -> SerpResult:
        if not self.domain:
            self.domain = urlparse(self.url).hostname or ""
        return self


class CompetitorPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain: str
    url: str
    title: str = ""
    meta_description: str = ""
    h_tags: dict[str, list[str]] = Field(default_factory=dict)
    word_count: int = 0
    schema_types: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Gaps and backlog
# ---------------------------------------------------------------------------


class Gap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keyword: str
    cluster_id: str = ""
    gap_type: GapType
    evidence: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    target: str | None = None

    @property
    def source_count(self) -> int:
        if self.sources:
            return len(set(self.sources))
        raw = self.evidence.get("sources", [])
        return len(set(raw)) if isinstance(raw, (list, tuple, set)) else 0


class BacklogItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_id: str
    kind: str
    target: str
    priority: float
    effort: int
    impact: int
    status: str = "open"
    confidence: float = 1.0
    evidence: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    gap_type: str = ""


class AuditDiff(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score_delta: float | None = None
    new_items: list[str] = Field(default_factory=list)
    closed_items: list[str] = Field(default_factory=list)
    new_gaps: list[str] = Field(default_factory=list)
    closed_gaps: list[str] = Field(default_factory=list)


class RunReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    status: str = "ok"
    site_score: float = 0.0
    grade: str = "F"
    generated_at: str = ""
    report_markdown: str = ""
    backlog: list[BacklogItem] = Field(default_factory=list)
    diff: AuditDiff = Field(default_factory=AuditDiff)
    budgets: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AuditDiff",
    "AuditSnapshot",
    "BacklogItem",
    "Cluster",
    "CompetitorPage",
    "Gap",
    "GapType",
    "Intent",
    "Keyword",
    "PageData",
    "RunReport",
    "SEOIssue",
    "SerpResult",
    "Severity",
    "SiteProfile",
]
