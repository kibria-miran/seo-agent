"""Backlog scoring and ranking (section 8.4).

Pure function: the same gaps produce byte-identical backlog items. The LLM
never sets a priority, an effort or a rank (D-2).
"""

from __future__ import annotations

from typing import Iterable, Sequence

from src import config
from src.models import BacklogItem, Gap, GapType

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
    return round((impact * confidence) / effort, 4)


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
        return f"Fix title/H1 coverage for '{keyword}' on {target}"
    if gap.gap_type == GapType.SCHEMA_MISSING:
        return f"Add missing schema to {target}"
    if gap.gap_type == GapType.COMP_COVERS:
        return f"Cover competitor topic '{keyword}'"
    return f"Address {gap.gap_type.value} for '{keyword}'"


def _dedupe_key(gap: Gap) -> tuple[str, str, str]:
    return (_normalise_keyword(gap.keyword), gap.gap_type.value, _target_for(gap))


def build_backlog(
    gaps: Sequence[Gap],
    money_keywords: Iterable[str] = (),
    max_items: int | None = None,
) -> list[BacklogItem]:
    """Score, de-duplicate, sort and cap gaps.

    Sort order is total: priority desc, effort asc, target asc, kind asc, then
    keyword asc. That guarantees identical output across runs (D-9).
    """

    money = tuple(money_keywords)
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
        if existing is None or candidate[0] > existing[0]:
            best[key] = candidate

    ordered = sorted(
        best.values(),
        key=lambda c: (
            -c[0],
            c[3],
            c[2].casefold(),
            _KIND_BY_TYPE.get(c[1].gap_type, "create_page"),
            _normalise_keyword(c[1].keyword),
            c[1].gap_type.value,
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
