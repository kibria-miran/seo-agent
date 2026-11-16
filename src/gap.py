"""Keyword-to-page coverage and competitor gaps (section 8.3).

Pure code. Every gap carries evidence so a human can see why it exists.
``analyze`` never calls an LLM.

Gap policy for an uncovered cluster
-----------------------------------
1. A city mentioned in the cluster -> ``LOCAL_MISSING``.
2. A page whose URL slug clearly targets the cluster but whose title/H1 miss
   the head term -> ``WEAK_PAGE`` (reuses the coverage stemmer, I-9).
3. At least two competitor domains cover it -> ``COMP_COVERS``.
4. Otherwise -> ``NO_PAGE``.

This gives each uncovered cluster exactly one coverage gap, plus independent
``SCHEMA_MISSING`` gaps for pages that lack all required schema types.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from src import config
from src.keywords import city_in, head_covered, head_terms, page_covers
from src.models import (
    AuditSnapshot,
    Cluster,
    CompetitorPage,
    Gap,
    GapType,
    PageData,
    SerpResult,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TYPE_ORDER = {
    GapType.WEAK_PAGE: 0,
    GapType.SCHEMA_MISSING: 1,
    GapType.LOCAL_MISSING: 2,
    GapType.COMP_COVERS: 3,
    GapType.NO_PAGE: 4,
}


def slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.casefold()).strip("-")


def _page_text(page: PageData) -> str:
    return " ".join([page.title or "", " ".join(page.h1_tags)])


def _competitor_text(page: CompetitorPage) -> str:
    return " ".join([page.title or "", " ".join(page.h_tags.get("h1", []))])


def candidate_page(cluster: Cluster, pages: Sequence[PageData]) -> PageData | None:
    """Best URL-slug match for a cluster, used for WEAK_PAGE detection."""

    wanted = head_terms(cluster.head_term)
    if not wanted:
        return None
    best: PageData | None = None
    best_overlap = 0
    for page in sorted(pages, key=lambda item: item.url):
        if page.status_code and page.status_code != 200:
            continue
        slug_terms = set(t for t in _SLUG_RE.split(page.url.casefold()) if t)
        overlap = len(wanted & slug_terms)
        if overlap > best_overlap:
            best = page
            best_overlap = overlap
    return best


def competitor_matches(
    head_term: str, competitor_pages: Sequence[CompetitorPage]
) -> list[CompetitorPage]:
    return [
        page
        for page in sorted(competitor_pages, key=lambda item: (item.domain, item.url))
        if head_covered(head_term, _competitor_text(page))
    ]


def serp_matches(head_term: str, serp: Sequence[SerpResult]) -> list[SerpResult]:
    return [
        result
        for result in sorted(serp, key=lambda item: (item.query, item.rank, item.url))
        if head_covered(head_term, f"{result.query} {result.title}")
    ]


def _cluster_keywords(cluster: Cluster) -> list[str]:
    return sorted(set(cluster.keywords or [cluster.head_term]))


def _coverage_gap(
    cluster: Cluster,
    pages: Sequence[PageData],
    competitor_pages: Sequence[CompetitorPage],
    serp: Sequence[SerpResult],
    cities: Sequence[str],
) -> Gap | None:
    head = cluster.head_term
    if not head:
        return None

    city = city_in(head, tuple(cities))
    if city:
        evidence = {
            "city": city,
            "service": head,
            "pages": sorted(page.url for page in pages),
        }
        return Gap(
            keyword=head,
            cluster_id=cluster.cluster_id,
            gap_type=GapType.LOCAL_MISSING,
            evidence=evidence,
            sources=["keywords", "cities"],
            target=f"/{slugify(head)}",
        )

    weak = candidate_page(cluster, pages)
    if weak is not None and not page_covers(head, weak):
        return Gap(
            keyword=head,
            cluster_id=cluster.cluster_id,
            gap_type=GapType.WEAK_PAGE,
            evidence={
                "page": weak.url,
                "title": weak.title,
                "h1": weak.h1_tags,
                "head_term": head,
            },
            sources=[],  # audit rule -> confidence 1.0
            target=weak.url,
        )

    comps = competitor_matches(head, competitor_pages)
    domains = sorted({page.domain for page in comps})
    serps = serp_matches(head, serp)

    if len(domains) >= 2:
        sources = ["keywords", *domains]
        return Gap(
            keyword=head,
            cluster_id=cluster.cluster_id,
            gap_type=GapType.COMP_COVERS,
            evidence={
                "competitors": sorted(page.url for page in comps),
                "domains": domains,
                "cluster_keywords": _cluster_keywords(cluster),
                "serp": [result.url for result in serps],
            },
            sources=sources,
            target=f"/{slugify(head)}",
        )

    sources = ["keywords"]
    if serps:
        sources.append("serp")
    if comps:
        sources.append("competitors")
    return Gap(
        keyword=head,
        cluster_id=cluster.cluster_id,
        gap_type=GapType.NO_PAGE,
        evidence={
            "pages": sorted(page.url for page in pages),
            "cluster_keywords": _cluster_keywords(cluster),
            "serp": [result.url for result in serps],
            "competitors": sorted(page.url for page in comps),
        },
        sources=sources,
        target=f"/{slugify(head)}",
    )


def _schema_gaps(
    pages: Sequence[PageData], required_schema: Sequence[str]
) -> list[Gap]:
    gaps: list[Gap] = []
    required = tuple(required_schema)
    for page in sorted(pages, key=lambda item: item.url):
        if page.status_code and page.status_code != 200:
            continue
        if any(schema in required for schema in page.schema_types):
            continue
        gaps.append(
            Gap(
                keyword=page.title or page.url,
                cluster_id="",
                gap_type=GapType.SCHEMA_MISSING,
                evidence={
                    "page": page.url,
                    "schema_types": list(page.schema_types),
                    "required": list(required),
                },
                sources=[],  # audit rule -> confidence 1.0
                target=page.url,
            )
        )
    return gaps


def analyze(
    audit: AuditSnapshot,
    clusters: Sequence[Cluster],
    competitor_pages: Sequence[CompetitorPage] = (),
    serp: Sequence[SerpResult] = (),
    *,
    cities: Iterable[str] | None = None,
    required_schema: Sequence[str] = ("LocalBusiness", "FinancialService", "FAQPage"),
) -> list[Gap]:
    """Return deterministic, evidence-backed gaps for one audit snapshot."""

    city_values = tuple(cities or config.UK_CITIES)
    pages = list(audit.pages)

    unique_clusters: dict[str, Cluster] = {}
    for cluster in sorted(clusters, key=lambda item: (item.cluster_id, item.head_term)):
        unique_clusters.setdefault(cluster.cluster_id, cluster)

    gaps: list[Gap] = []
    for cluster in sorted(unique_clusters.values(), key=lambda item: item.cluster_id):
        if any(page_covers(cluster.head_term, page) for page in pages):
            continue
        gap = _coverage_gap(cluster, pages, competitor_pages, serp, city_values)
        if gap is not None:
            gaps.append(gap)

    gaps.extend(_schema_gaps(pages, required_schema))

    return sorted(
        gaps,
        key=lambda gap: (
            _TYPE_ORDER.get(gap.gap_type, 99),
            gap.keyword.casefold(),
            gap.target or "",
            gap.cluster_id,
        ),
    )


__all__ = [
    "analyze",
    "candidate_page",
    "competitor_matches",
    "serp_matches",
    "slugify",
]
