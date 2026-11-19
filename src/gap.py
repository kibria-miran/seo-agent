"""Keyword-to-page coverage and competitor gaps (section 8.3).

Pure code. Every gap carries evidence so a human can see why it exists.
``analyze`` never calls an LLM.

Gap policy for an uncovered cluster
-----------------------------------
1. A city mentioned in the cluster -> ``LOCAL_MISSING``.
2. A page whose URL slug clearly targets the cluster but whose title/H1 miss
   the head term -> ``WEAK_PAGE`` (reuses the coverage stemmer, I-9).
2b. The N-5 pre-check: any crawled page with >=2 significant head-term
    tokens across title + H1 + H2 combined (N-14, stoplist per N-15) ->
    ``WEAK_PAGE`` for that page, ahead of ``NO_PAGE``.
3. At least two competitor domains cover it -> ``COMP_COVERS``.
4. Otherwise -> ``NO_PAGE``.

This gives each uncovered cluster exactly one coverage gap, plus
``SCHEMA_MISSING`` gaps for keyword-relevant pages (slug overlap with a
cluster head term, or title/H1 coverage) that lack all required schema
types. Pages no cluster can reach are not flagged: schema evidence must
discriminate, or the backlog degenerates into one schema warning per page.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from src import config
from src.keywords import (
    city_in,
    head_covered,
    head_terms,
    normalise,
    page_covers,
    precheck_field_tokens,
    precheck_terms,
)
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


def content_match_page(
    head: str, pages: Sequence[PageData]
) -> tuple[PageData, set[str], dict[str, list[str]]] | None:
    """Best page matching the N-5 pre-check for ``head`` (N-14: fields combined).

    Returns the page, the matched significant tokens and the per-field hits,
    or None when no page has at least two significant head-term tokens across
    title + H1 + H2 combined. Deterministic: most matched tokens, then URL.
    """

    wanted = precheck_terms(head)
    if len(wanted) < 2:
        return None
    best: tuple[PageData, set[str], dict[str, list[str]]] | None = None
    for page in pages:
        field_tokens = precheck_field_tokens(page)
        matched = wanted & (set().union(*field_tokens.values()) if field_tokens else set())
        if len(matched) < 2:
            continue
        fields = {
            name: sorted(matched & toks)
            for name, toks in field_tokens.items()
            if matched & toks
        }
        if best is None or len(matched) > len(best[1]) or (
            len(matched) == len(best[1]) and page.url < best[0].url
        ):
            best = (page, matched, fields)
    return best


def candidate_page(cluster: Cluster, pages: Sequence[PageData]) -> PageData | None:
    """Best URL-slug match for a cluster, used for WEAK_PAGE detection."""

    wanted = head_terms(cluster.head_term)
    if not wanted:
        return None
    min_overlap = min(config.WEAK_PAGE_MIN_SLUG_OVERLAP, len(wanted))
    best: PageData | None = None
    best_overlap = 0
    for page in sorted(pages, key=lambda item: item.url):
        if page.status_code and page.status_code != 200:
            continue
        slug_terms = {t for t in _SLUG_RE.split(page.url.casefold()) if t}
        overlap = len(wanted & slug_terms)
        if overlap >= min_overlap and overlap > best_overlap:
            best = page
            best_overlap = overlap
    return best


def nearest_pages(cluster: Cluster, pages: Sequence[PageData], limit: int = 5) -> list[str]:
    """Pages closest (by slug-term overlap) to the cluster, capped and stable.

    Alphabetical fill after overlap-scored candidates keeps a run byte-stable
    while trimming the full page census from evidence blobs.
    """

    wanted = head_terms(cluster.head_term) if cluster.head_term else set()
    if not wanted:
        return sorted(page.url for page in pages)[:limit]

    scored = sorted(
        pages,
        key=lambda page: (-len(wanted & set(_SLUG_RE.split(page.url.casefold()))), page.url),
    )
    matched = [page for page in scored if wanted & set(_SLUG_RE.split(page.url.casefold()))]
    chosen = (matched or scored)[:limit]
    return sorted(page.url for page in chosen)


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


def _gsc_pages_for(
    cluster: Cluster,
    query_page_map: Mapping[str, Sequence[str]] | None,
) -> list[str]:
    if not query_page_map:
        return []
    wanted = {normalise(kw) for kw in _cluster_keywords(cluster)}
    wanted.add(normalise(cluster.head_term))
    pages: set[str] = set()
    for query, mapped in query_page_map.items():
        if normalise(query) in wanted:
            pages.update(mapped)
    return sorted(pages)


def _gsc_demand_for(
    cluster: Cluster,
    gsc_demand: Mapping[str, Mapping[str, float | None]] | None,
) -> dict[str, float | int] | None:
    if not gsc_demand:
        return None
    wanted = {normalise(kw) for kw in _cluster_keywords(cluster)}
    wanted.add(normalise(cluster.head_term))
    clicks = 0.0
    impressions = 0.0
    position: float | None = None
    queries = 0
    for key, metrics in gsc_demand.items():
        if normalise(key) not in wanted:
            continue
        queries += 1
        clicks += float(metrics.get("clicks") or 0.0)
        impressions += float(metrics.get("impressions") or 0.0)
        raw_position = metrics.get("position")
        if raw_position is not None:
            value = float(raw_position)
            position = value if position is None else min(position, value)
    if queries == 0:
        return None
    demand: dict[str, float | int] = {
        "clicks": round(clicks, 4),
        "impressions": round(impressions, 4),
        "queries": queries,
    }
    if impressions > 0:
        demand["ctr"] = round(clicks / impressions, 6)
    if position is not None:
        demand["position"] = round(position, 4)
    return demand


def _coverage_gap(
    cluster: Cluster,
    pages: Sequence[PageData],
    competitor_pages: Sequence[CompetitorPage],
    serp: Sequence[SerpResult],
    cities: Sequence[str],
    query_page_map: Mapping[str, Sequence[str]] | None = None,
    gsc_demand: Mapping[str, Mapping[str, float | None]] | None = None,
) -> Gap | None:
    head = cluster.head_term
    if not head:
        return None

    gsc_pages = _gsc_pages_for(cluster, query_page_map)
    gsc = _gsc_demand_for(cluster, gsc_demand)
    gsc_evidence = {"gsc": gsc} if gsc else {}

    city = city_in(head, tuple(cities))
    if city:
        evidence = {
            "city": city,
            "service": head,
            "pages": nearest_pages(cluster, pages),
            **gsc_evidence,
        }
        if gsc_pages:
            evidence["gsc_pages"] = gsc_pages
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
                **gsc_evidence,
                **({"gsc_pages": gsc_pages} if gsc_pages else {}),
            },
            sources=[],  # audit rule -> confidence 1.0
            target=weak.url,
        )

    weak_content = content_match_page(head, pages)
    if weak_content is not None:
        match_page, matched, matched_fields = weak_content
        return Gap(
            keyword=head,
            cluster_id=cluster.cluster_id,
            gap_type=GapType.WEAK_PAGE,
            evidence={
                "page": match_page.url,
                "title": match_page.title,
                "h1": match_page.h1_tags,
                "h2": match_page.h2_tags,
                "head_term": head,
                "matched_tokens": sorted(matched),
                "matched_fields": matched_fields,
                **gsc_evidence,
                **({"gsc_pages": gsc_pages} if gsc_pages else {}),
            },
            sources=[],  # audit rule -> confidence 1.0
            target=match_page.url,
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
                **gsc_evidence,
                **({"gsc_pages": gsc_pages} if gsc_pages else {}),
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
            "pages": nearest_pages(cluster, pages),
            "cluster_keywords": _cluster_keywords(cluster),
            "serp": [result.url for result in serps],
            "competitors": sorted(page.url for page in comps),
            **gsc_evidence,
            **({"gsc_pages": gsc_pages} if gsc_pages else {}),
        },
        sources=sources,
        target=f"/{slugify(head)}",
    )


def _page_relevant(page: PageData, clusters: Sequence[Cluster]) -> bool:
    """True when a page is plausibly a target for at least one cluster.

    Slug-term overlap (same rule as candidate_page) or title/H1 coverage.
    SCHEMA_MISSING is demand-relevant evidence, not a site-wide lint: pages
    no keyword cluster can reach are not worth a schema nag in the backlog.
    """

    slug_terms = {t for t in _SLUG_RE.split(page.url.casefold()) if t}
    for cluster in clusters:
        head = cluster.head_term
        if not head:
            continue
        if head_terms(head) & slug_terms:
            return True
        if page_covers(head, page):
            return True
    return False


def _path_of(url: str) -> str:
    """Readable page identifier for gaps that describe a page, not a keyword."""

    try:
        path = urlsplit(url or "").path.rstrip("/")
    except ValueError:
        return url or ""
    return path or "/"


def _schema_gaps(
    pages: Sequence[PageData],
    required_schema: Sequence[str],
    relevant_urls: set[str],
) -> list[Gap]:
    gaps: list[Gap] = []
    required = tuple(required_schema)
    for page in sorted(pages, key=lambda item: item.url):
        if page.status_code and page.status_code != 200:
            continue
        if page.url not in relevant_urls:
            continue
        if any(schema in required for schema in page.schema_types):
            continue
        gaps.append(
            Gap(
                # A schema gap is page-level, not keyword-level. Using the page
                # title here made the report list "Buy-to-Let Mortgages | Easy
                # Financial Services" as if it were a search term.
                keyword=_path_of(page.url),
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
    query_page_map: Mapping[str, Sequence[str]] | None = None,
    gsc_demand: Mapping[str, Mapping[str, float | None]] | None = None,
) -> list[Gap]:
    """Return deterministic, evidence-backed gaps for one audit snapshot."""

    city_values = tuple(cities or config.UK_CITIES)
    pages = list(audit.pages)

    unique_clusters: dict[str, Cluster] = {}
    for cluster in sorted(clusters, key=lambda item: (item.cluster_id, item.head_term)):
        unique_clusters.setdefault(cluster.cluster_id, cluster)

    gaps: list[Gap] = []
    ordered_clusters = sorted(unique_clusters.values(), key=lambda item: item.cluster_id)
    for cluster in ordered_clusters:
        if any(page_covers(cluster.head_term, page) for page in pages):
            continue
        gap = _coverage_gap(
            cluster, pages, competitor_pages, serp, city_values, query_page_map, gsc_demand
        )
        if gap is not None:
            gaps.append(gap)

    relevant_urls = {
        page.url for page in pages if _page_relevant(page, ordered_clusters)
    }
    gaps.extend(_schema_gaps(pages, required_schema, relevant_urls))

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
