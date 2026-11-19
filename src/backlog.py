"""Backlog scoring and ranking (section 8.4).

Pure function: the same gaps produce byte-identical backlog items. The LLM
never sets a priority, an effort or a rank (D-2).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from src import config
from src.models import BacklogItem, Gap, GapType

_SCHEMA_REQUIRED_UNION_KEY = "required"


def demand_multiplier(gap: Gap) -> float:
    """GSC demand boost: scale priority when the cluster carries search volume."""

    evidence = gap.evidence or {}
    gsc = evidence.get("gsc") if isinstance(evidence, dict) else None
    if not isinstance(gsc, dict):
        return 1.0
    impressions = gsc.get("impressions")
    if impressions is None:
        return 1.0
    value = float(impressions or 0.0)
    if value >= config.GSC_BOOST_TIER_1_IMPRESSIONS:
        return config.GSC_BOOST_TIER_1
    if value >= config.GSC_BOOST_TIER_2_IMPRESSIONS:
        return config.GSC_BOOST_TIER_2
    if value >= config.GSC_BOOST_TIER_3_IMPRESSIONS:
        return config.GSC_BOOST_TIER_3
    return 1.0


_SEVERITY_IMPACT = {
    "CRITICAL": config.IMPACT_CRITICAL,
    "WARNING": config.IMPACT_WARNING,
    "INFO": config.IMPACT_INFO,
}

_EFFORT_BY_TYPE = {
    GapType.WEAK_PAGE: config.EFFORT_META,
    GapType.SCHEMA_MISSING: config.EFFORT_SCHEMA,
    GapType.NO_PAGE: config.EFFORT_PAGE,
    GapType.LOCAL_MISSING: config.EFFORT_PAGE,
    GapType.COMP_COVERS: config.EFFORT_PAGE,
}

_KIND_BY_TYPE = {
    GapType.WEAK_PAGE: "meta_fix",
    GapType.SCHEMA_MISSING: "schema",
    GapType.NO_PAGE: "create_page",
    GapType.LOCAL_MISSING: "create_local_page",
    GapType.COMP_COVERS: "create_page",
}

_KIND_RANK = {
    "meta_fix": 0,
    "schema": 1,
    "create_local_page": 2,
    "create_page": 3,
}


def _normalise_keyword(value: str) -> str:
    return " ".join((value or "").casefold().split())


def impact_for(gap: Gap, money_keywords: Iterable[str] = ()) -> int:
    if gap.gap_type == GapType.NO_PAGE:
        money = {_normalise_keyword(k) for k in money_keywords}
        if _normalise_keyword(gap.keyword) in money:
            return config.IMPACT_CRITICAL
    severity = str(gap.evidence.get("severity", "")).upper()
    if severity in _SEVERITY_IMPACT:
        return _SEVERITY_IMPACT[severity]
    if gap.gap_type in (GapType.NO_PAGE, GapType.WEAK_PAGE, GapType.LOCAL_MISSING,
                        GapType.SCHEMA_MISSING, GapType.COMP_COVERS):
        return config.IMPACT_WARNING
    return config.IMPACT_INFO


def effort_for(gap: Gap) -> int:
    return _EFFORT_BY_TYPE.get(gap.gap_type, config.EFFORT_PAGE)


def confidence_for(gap: Gap) -> float:
    # Rules evaluated inside the audit are authoritative.
    if gap.gap_type in (GapType.WEAK_PAGE, GapType.SCHEMA_MISSING):
        return config.CONFIDENCE_AUDIT
    count = gap.source_count
    if count >= config.MULTI_SOURCE_THRESHOLD:
        return config.CONFIDENCE_MULTI_SOURCE
    if count == 2:
        return config.CONFIDENCE_DUAL_SOURCE
    return config.CONFIDENCE_SINGLE_SOURCE


def priority_for(gap: Gap, money_keywords: Iterable[str] = ()) -> float:
    """priority = (impact * confidence) / effort, rounded deterministically."""

    impact = impact_for(gap, money_keywords)
    confidence = confidence_for(gap)
    effort = effort_for(gap)
    return round((impact * confidence / effort) * demand_multiplier(gap), 4)


def _target_for(gap: Gap) -> str:
    if gap.target:
        return gap.target
    evidence_target = gap.evidence.get("target")
    if isinstance(evidence_target, str) and evidence_target:
        return evidence_target
    return gap.keyword


def _title_for(gap: Gap, target: str) -> str:
    keyword = gap.keyword
    if gap.gap_type == GapType.NO_PAGE:
        return f"Create a page targeting '{keyword}'"
    if gap.gap_type == GapType.LOCAL_MISSING:
        return f"Create a local page for '{keyword}'"
    if gap.gap_type == GapType.WEAK_PAGE:
        count = gap.evidence.get("keyword_count") if isinstance(gap.evidence, dict) else None
        if isinstance(count, int) and count > 1:
            return f"Fix title/H1 coverage on {target} ({count} keywords)"
        return f"Fix title/H1 coverage for '{keyword}' on {target}"
    if gap.gap_type == GapType.SCHEMA_MISSING:
        page_count = gap.evidence.get("page_count") if isinstance(gap.evidence, dict) else None
        if page_count:
            money_count = gap.evidence.get("money_page_count") if isinstance(gap.evidence, dict) else None
            if money_count:
                return (
                    f"Add missing schema to {page_count} keyword-relevant pages "
                    f"({money_count} money pages)"
                )
            return f"Add missing schema to {page_count} keyword-relevant pages"
        return f"Add missing schema to {target}"
    if gap.gap_type == GapType.COMP_COVERS:
        return f"Cover competitor topic '{keyword}'"
    return f"Address {gap.gap_type.value} for '{keyword}'"


def _dedupe_key(gap: Gap) -> tuple[str, str, str]:
    return (_normalise_keyword(gap.keyword), gap.gap_type.value, _target_for(gap))


def _normalise_url(value: str) -> str:
    return (value or "").casefold().rstrip("/")


def _gsc_impressions(gap: Gap) -> float:
    evidence = gap.evidence if isinstance(gap.evidence, dict) else {}
    gsc = evidence.get("gsc") if isinstance(evidence, dict) else None
    if not isinstance(gsc, dict):
        return 0.0
    try:
        return float(gsc.get("impressions") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_money_gap(gap: Gap, money_set: set[str]) -> bool:
    if gap.gap_type == GapType.SCHEMA_MISSING:
        evidence = gap.evidence if isinstance(gap.evidence, dict) else {}
        return bool(evidence.get("money_page_count"))
    return _normalise_keyword(gap.keyword) in money_set


def _money_kw_count(gap: Gap, money_set: set[str]) -> int:
    """Number of profile money keywords the item covers.

    An item is never itself a keyword: the sitewide SCHEMA_MISSING
    umbrella has no keyword set and counts 0 here, so the N-3 key never
    compares page counts against keyword counts.
    """

    evidence = gap.evidence if isinstance(gap.evidence, dict) else {}
    cluster = evidence.get("cluster_keywords")
    if isinstance(cluster, (list, tuple)) and cluster:
        terms = {_normalise_keyword(str(term)) for term in cluster}
    else:
        terms = {_normalise_keyword(gap.keyword)}
    return sum(1 for term in terms if term in money_set)


def _kind_rank(gap: Gap) -> int:
    kind = _KIND_BY_TYPE.get(gap.gap_type, "create_page")
    return _KIND_RANK.get(kind, len(_KIND_RANK))


def _content_key(gap: Gap) -> str:
    """Stable content digest; the terminal tiebreak in the N-3 order.

    Item ids are positional (BL-0001..) so they cannot order the items that
    produce them. The digest stands in for N-3's terminal ``item_id`` and
    keeps the order total even between byte-different findings on the same
    keyword and target.
    """

    evidence = gap.evidence if isinstance(gap.evidence, dict) else {}
    payload = {
        "keyword": _normalise_keyword(gap.keyword),
        "gap_type": gap.gap_type.value,
        "cluster_id": gap.cluster_id,
        "target": _target_for(gap).casefold(),
        "evidence": evidence,
        "sources": sorted(set(gap.sources)),
    }
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _merge_page_weak_gaps(
    entries: dict[tuple[str, str, str], tuple[float, Gap, str, int, int, float]],
) -> dict[tuple[str, str, str], tuple[float, Gap, str, int, int, float]]:
    """Collapse WEAK_PAGE gaps that share a page into one actionable item.

    Eight keywords pointing at ``/services`` are one title/H1 edit, not eight
    sprint items. The merged item keeps the strongest keyword's priority and
    records the full keyword set, so money-keyword coverage still counts.
    Deterministic: groups and representatives are ordered, never sampled.
    """

    groups: dict[str, list[tuple[float, Gap, str, int, int, float]]] = {}
    for _key, candidate in entries.items():
        if candidate[1].gap_type != GapType.WEAK_PAGE:
            continue
        groups.setdefault(_normalise_url(_target_for(candidate[1])), []).append(candidate)

    merged = dict(entries)
    for target_key in sorted(groups):
        group = groups[target_key]
        if len(group) < 2:
            continue
        group.sort(key=lambda c: (-c[0], _content_key(c[1])))
        priority, source, target, effort, impact, confidence = group[0]
        keywords = sorted({_normalise_keyword(c[1].keyword) for c in group})
        evidence = dict(source.evidence)
        evidence["keywords"] = keywords
        evidence["keyword_count"] = len(keywords)
        evidence["cluster_keywords"] = keywords
        for candidate in group:
            merged.pop(_dedupe_key(candidate[1]), None)
        combined = Gap(
            keyword=source.keyword,
            cluster_id=source.cluster_id,
            gap_type=GapType.WEAK_PAGE,
            evidence=evidence,
            sources=list(source.sources),
            target=target,
        )
        merged[_dedupe_key(combined)] = (priority, combined, target, effort, impact, confidence)
    return merged


def build_backlog(
    gaps: Sequence[Gap],
    money_keywords: Iterable[str] = (),
    max_items: int | None = None,
    money_urls: Iterable[str] | None = None,
) -> list[BacklogItem]:
    """Score, de-duplicate, sort and cap gaps.

    Sort order is total and deterministic under input shuffling (N-3):
    priority desc, money keyword first, GSC impressions desc, money keyword
    count desc, kind rank asc (meta_fix, schema, create_local_page,
    create_page), then target asc, keyword asc, gap_type asc and finally a
    content digest asc. Item ids are assigned positionally after sorting.
    Tiebreaks change order only, never the priority value (N-4).
    """

    money = tuple(money_keywords)
    money_set = {_normalise_keyword(k) for k in money}
    money_url_set = {_normalise_url(u) for u in (money_urls or ())}
    limit = config.MAX_BACKLOG if max_items is None else max(0, int(max_items))

    best: dict[tuple[str, str, str], tuple[float, Gap, str, int, int, float]] = {}
    for gap in gaps:
        key = _dedupe_key(gap)
        target = _target_for(gap)
        impact = impact_for(gap, money)
        effort = effort_for(gap)
        confidence = confidence_for(gap)
        priority = priority_for(gap, money)
        candidate = (priority, gap, target, effort, impact, confidence)
        existing = best.get(key)
        if (
            existing is None
            or candidate[0] > existing[0]
            or (candidate[0] == existing[0] and _content_key(gap) < _content_key(existing[1]))
        ):
            best[key] = candidate

    best = _merge_page_weak_gaps(best)

    schema_entries = [c for c in best.values() if c[1].gap_type == GapType.SCHEMA_MISSING]
    if len(schema_entries) > config.SCHEMA_UMBRELLA_MIN_PAGES:
        pages = sorted({c[2] for c in schema_entries})
        required = sorted(
            {
                schema
                for c in schema_entries
                for schema in (c[1].evidence.get("required", []) if isinstance(c[1].evidence, dict) else [])
            }
        )
        money_pages = sorted(p for p in pages if _normalise_url(p) in money_url_set)
        umbrella = Gap(
            keyword="schema",
            cluster_id="",
            gap_type=GapType.SCHEMA_MISSING,
            evidence={
                "page_count": len(pages),
                "pages": pages,
                "required": required,
                "money_pages": money_pages,
                "money_page_count": len(money_pages),
            },
            sources=[],
            target="sitewide",
        )
        effort = max(
            config.EFFORT_SCHEMA, min(len(pages), config.SCHEMA_UMBRELLA_MAX_EFFORT)
        )
        impact = config.IMPACT_CRITICAL if money_pages else config.IMPACT_WARNING
        confidence = config.CONFIDENCE_AUDIT
        priority = round(impact * confidence / effort, 4)
        for key in [k for k, c in best.items() if c[1].gap_type == GapType.SCHEMA_MISSING]:
            del best[key]
        best[("schema", GapType.SCHEMA_MISSING.value, "sitewide")] = (
            priority,
            umbrella,
            "sitewide",
            effort,
            impact,
            confidence,
        )

    ordered = sorted(
        best.values(),
        key=lambda c: (
            -c[0],
            -int(_is_money_gap(c[1], money_set)),
            -_gsc_impressions(c[1]),
            -_money_kw_count(c[1], money_set),
            _kind_rank(c[1]),
            c[2].casefold(),
            _normalise_keyword(c[1].keyword),
            c[1].gap_type.value,
            _content_key(c[1]),
        ),
    )[:limit]

    items: list[BacklogItem] = []
    for index, (priority, gap, target, effort, impact, confidence) in enumerate(
        ordered, start=1
    ):
        items.append(
            BacklogItem(
                item_id=f"BL-{index:04d}",
                kind=_KIND_BY_TYPE.get(gap.gap_type, "create_page"),
                target=target,
                priority=priority,
                effort=effort,
                impact=impact,
                confidence=confidence,
                evidence=dict(gap.evidence),
                title=_title_for(gap, target),
                gap_type=gap.gap_type.value,
            )
        )
    return items


__all__ = [
    "build_backlog",
    "confidence_for",
    "effort_for",
    "impact_for",
    "priority_for",
]
