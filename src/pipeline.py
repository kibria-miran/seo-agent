"""Deterministic (no-LLM) pipeline: fixture in, report + backlog out.

This is Phase 1's end-to-end path. It is deliberately not the agent loop: no
planner, no LLM, no network when a fixture is supplied. The agent loop in
Phase 6 will call the same tools and persist through the same Store.

D-12: the whole pipeline runs with zero LLM calls.
D-9: the same run_id, fixture and injected clock produce byte-identical files.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src import clock, config
from src.audit_adapter import fetch_budget_exhausted, fetch_count, run_audit
from src.backlog import build_backlog
from src.drafts import write_drafts
from src.gap import analyze
from src.keywords import city_in, cluster, intent_for, normalise
from src.models import (
    AuditDiff,
    AuditSnapshot,
    BacklogItem,
    Cluster,
    CompetitorPage,
    Gap,
    Intent,
    Keyword,
    RunReport,
    SerpResult,
    SiteProfile,
)
from src.report import render_report, write_report
from src.store import Store
from src.trace import TraceWriter


def load_profile(path: str | Path) -> SiteProfile:
    profile_path = Path(path)
    if profile_path.is_absolute() or profile_path.exists():
        candidate = profile_path
    else:
        # ``config.PROFILES_DIR`` is the directory that contains site.json, so
        # a bare ``profiles/site.json`` (the CLI default) resolves against it.
        # Fall back to joining the full relative path for callers that pass a
        # root-relative value.
        candidate = config.PROFILES_DIR / Path(path).name
        if not candidate.exists():
            candidate = config.PROFILES_DIR / path
    if not candidate.exists():
        raise FileNotFoundError(f"site profile not found: {candidate}")
    data = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"site profile must be a JSON object: {candidate}")
    return SiteProfile(**data)


def build_keywords(profile: SiteProfile) -> list[Keyword]:
    """Turn the hand-written target list into Keyword models (no network)."""

    cities = tuple(profile.cities)
    keywords: list[Keyword] = []
    for raw in profile.target_keywords:
        value = normalise(raw)
        if not value:
            continue
        keywords.append(
            Keyword(
                keyword=value,
                source="profile",
                intent=Intent(intent_for(value, cities)),
                city=city_in(value, cities),
            )
        )
    return sorted(keywords, key=lambda item: (item.keyword, item.source))


def money_keywords_for(profile: SiteProfile) -> list[str]:
    """Derive money keywords from the profile's money-page slugs.

    Treating every target keyword as a money keyword would make the CRITICAL
    impact rule meaningless. ``/free-mortgage-advice`` -> "free mortgage
    advice"; the homepage contributes nothing.
    """

    values: set[str] = set()
    for path in profile.money_pages:
        if path == "/":
            continue
        value = normalise(path.strip("/").replace("-", " "))
        if value:
            values.add(value)
    return sorted(values)


def mine_scraping_sources(
    profile: SiteProfile,
    store: Store,
    trace: TraceWriter,
) -> tuple[list[Keyword], list[SerpResult], list[CompetitorPage], dict[str, int]]:
    """Opt-in scraping demand/evidence mining (D-3, D-14).

    Google Suggest and DuckDuckGo HTML are keyless but ToS-grey; these run
    only when the owner passes ``--with-scraping`` (off by default). Returns
    ``(keywords, serp_results, counts)`` where counts maps each source to the
    number of items it contributed. A source that fails transport or parsing
    is recorded in the trace and skipped; a source whose declared requirement
    is missing is logged as ``dep_unmet``. Neither stops the run.
    """

    from src.sources import fetch as sources_fetch
    from src.sources.base import SourceError
    from src.sources.competitor import mine_competitors
    from src.sources.serp import SerpSource
    from src.sources.suggest import SuggestSource, seed_terms

    fetch_start = sources_fetch.fetch_count()
    keywords: list[Keyword] = []
    serp_results: list[SerpResult] = []
    counts = {"suggest": 0, "serp": 0, "competitor_pages": 0}

    # Reserve fetch budget for competitor mining so suggest/serp can't starve it
    # (D-13: budgets enforced in code, never by prompts).
    competitor_reserve = (
        config.MAX_SERP_QUERIES
        + config.MAX_COMP_PAGES * len(profile.competitors)
        + len(profile.competitors)
    )

    suggest = SuggestSource()
    suggest_empty = 0
    for seed in seed_terms(profile):
        if sources_fetch.fetch_count() >= config.MAX_FETCHES - competitor_reserve:
            break
        try:
            result = suggest.collect(seed, store=store, trace=trace)
        except SourceError as exc:
            trace.emit(step="sources", tool="suggest", args={"query": seed},
                       source="net", status="error", kind="action",
                       error_type=type(exc).__name__)
            break
        if not result.skipped and not result.items:
            suggest_empty += 1
        mined = SuggestSource.to_keywords(result.items, cities=profile.cities)
        keywords.extend(mined)
        counts["suggest"] += len(mined)
    counts["suggest_empty"] = suggest_empty

    serp = SerpSource()
    serp_empty = 0
    for query in profile.target_keywords[: config.MAX_SERP_QUERIES]:
        if sources_fetch.fetch_count() >= config.MAX_FETCHES - competitor_reserve:
            break
        try:
            result = serp.collect(query, store=store, trace=trace)
        except SourceError as exc:
            trace.emit(step="sources", tool="serp", args={"query": query},
                       source="net", status="error", kind="action",
                       error_type=type(exc).__name__)
            break
        if not result.skipped and not result.items:
            serp_empty += 1
        found = SerpSource.to_serp_results(result.items)
        serp_results.extend(found)
        counts["serp"] += len(found)
    counts["serp_empty"] = serp_empty

    competitor_pages = mine_competitors(profile, store=store, trace=trace)
    counts["competitor_pages"] = len(competitor_pages)

    fetches = sources_fetch.fetch_count() - fetch_start
    trace.emit(step="sources", tool="mine_sources", args={"fetches": fetches},
               source="net", status="ok", kind="action")
    counts = dict(counts)
    counts["fetches"] = fetches
    return keywords, serp_results, competitor_pages, counts


def mine_file_sources(
    profile: SiteProfile,
    store: Store,
    trace: TraceWriter,
) -> tuple[list[Keyword], dict[str, int]]:
    """File-based GSC ingest (``SEO_AGENT_GSC_CSV``). Never touches the network.

    Returns ``(keywords, counts)``. An unmet requirement is logged as
    ``dep_unmet`` and skipped; a configured-but-missing file is logged as an
    error; either way the run continues.
    """

    from src.sources.base import SourceError
    from src.sources.gsc_csv import GscCsvSource

    keywords: list[Keyword] = []
    counts = {"gsc_csv": 0}
    gsc = GscCsvSource()
    try:
        result = gsc.collect("queries", store=store, trace=trace)
        mined = GscCsvSource.to_keywords(result.items, cities=profile.cities)
        keywords.extend(mined)
        counts["gsc_csv"] = len(mined)
    except SourceError as exc:
        trace.emit(step="sources", tool="gsc_csv", args={},
                   source="file", status="error", kind="action",
                   error_type=type(exc).__name__)
    return keywords, counts


def mine_gsc_pages(
    store: Store,
    trace: TraceWriter,
) -> tuple[dict[str, list[str]], str]:
    """Optional query→page mapping from the GSC pages CSV (D-3, D-14).

    Returns ``(mapping, status)`` where status is ``ok``, ``dep_unmet`` or
    ``error``. Never raises; the run continues without the enrichment.
    """

    from src.sources.base import SourceError
    from src.sources.gsc_pages import GscPagesSource

    source = GscPagesSource()
    try:
        result = source.collect("pages", store=store, trace=trace)
    except SourceError as exc:
        trace.emit(step="sources", tool="gsc_pages", args={},
                   source="file", status="error", kind="action",
                   error_type=type(exc).__name__)
        return {}, "error"
    if result.skipped:
        return {}, "dep_unmet"
    return GscPagesSource.to_query_page_map(result.items), "ok"


def gsc_demand_for(
    keywords: list[Keyword],
) -> dict[str, dict[str, float | None]]:
    """Demand map from GSC-fed keywords: normalised keyword -> metrics."""

    demand: dict[str, dict[str, float | None]] = {}
    for item in keywords:
        if item.gsc_impressions is None and item.gsc_clicks is None:
            continue
        demand[normalise(item.keyword)] = {
            "clicks": item.gsc_clicks,
            "impressions": item.gsc_impressions,
            "ctr": item.gsc_ctr,
            "position": item.gsc_position,
        }
    return demand


def merge_keywords(primary: list[Keyword], extra: list[Keyword]) -> list[Keyword]:
    """Union by (keyword, source); profile keywords first, then sorted."""

    seen = {(item.keyword, item.source) for item in primary}
    merged = list(primary)
    for item in extra:
        key = (item.keyword, item.source)
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return sorted(merged, key=lambda item: (item.keyword, item.source))


def build_clusters(keywords: list[Keyword]) -> list[Cluster]:
    clusters = cluster(keywords)
    membership = {
        keyword: item.cluster_id for item in clusters for keyword in item.keywords
    }
    for keyword in keywords:
        if keyword.cluster_id is None:
            keyword.cluster_id = membership.get(keyword.keyword)
    return clusters


def default_run_id() -> str:
    return "run-" + clock.now().strftime("%Y%m%dT%H%M%SZ")


def save_run_stages(
    store: Store,
    run_id: str,
    *,
    audit: AuditSnapshot,
    keywords: list[Keyword],
    serp: list[SerpResult],
    competitor_pages: list[CompetitorPage],
    gaps: list[Gap],
    backlog: list[BacklogItem],
) -> None:
    store.save_audit(run_id, audit)
    store.save_keywords(run_id, keywords)
    store.save_serp(run_id, serp)
    store.save_competitor_pages(run_id, competitor_pages)
    store.save_gaps(run_id, gaps)
    store.save_backlog(run_id, backlog)


def previous_baseline(
    store: Store, run_id: str, domain: str | None
) -> tuple[str | None, str | None]:
    row = store.latest_run(exclude=run_id, domain=domain, completed_only=True)
    previous_run_id = row["run_id"] if row else None
    host = config.normalize_domain(domain) or (domain or "").strip() or "unknown host"
    baseline_note = (
        None
        if previous_run_id or store.latest_run(exclude=run_id) is None
        else f"No comparable previous run for {host}."
    )
    return previous_run_id, baseline_note


def render_and_write_run(
    store: Store,
    run_id: str,
    *,
    audit: AuditSnapshot,
    keywords: list[Keyword],
    serp: list[SerpResult],
    competitor_pages: list[CompetitorPage],
    gaps: list[Gap],
    backlog: list[BacklogItem],
    analysis: Mapping[str, Mapping[str, str]] | None = None,
    drafts: dict[str, str],
    budgets: dict[str, Any],
    previous_run_id: str | None,
    baseline_note: str | None,
    generated_at: str,
    out_root: str | Path | None,
) -> tuple[dict[str, Path], str, AuditDiff]:
    diff = store.diff_runs(previous_run_id, run_id)
    run_row: dict[str, Any] = dict(store.get_run(run_id) or {})
    run_row["backlog_count"] = len(backlog)
    markdown = render_report(
        run_row,
        audit,
        diff=diff,
        backlog=backlog,
        gaps=gaps,
        analysis=analysis,
        keywords=keywords,
        serp=serp,
        competitor_pages=competitor_pages,
        drafts=sorted(drafts),
        budgets=budgets,
        previous_run_id=previous_run_id,
        baseline_note=baseline_note,
        generated_at=generated_at,
    )
    paths = write_report(run_id, markdown, backlog, drafts=drafts or None, out_root=out_root)
    budgets["outputs"] = {name: str(path) for name, path in sorted(paths.items())}
    return paths, markdown, diff


def run_deterministic(
    profile: SiteProfile,
    *,
    fixture_path: str | Path | None = None,
    run_id: str | None = None,
    db_path: str | Path | None = None,
    out_root: str | Path | None = None,
    trace_path: str | Path | None = None,
    with_sources: bool = False,
    with_scraping: bool = False,
    with_drafts: bool = False,
) -> RunReport:
    """Run audit -> keywords -> clusters -> gaps -> backlog -> report.

    A fixture path bypasses the network entirely. Without one, the vendored
    seoextract crawl is used (polite wrapper configured by the adapter).
    ``with_sources=True`` enables the file-based GSC ingest only;
    ``with_scraping=True`` enables the ToS-grey Google Suggest / DuckDuckGo
    SERP scraping and competitor discovery. Both are off by default; the
    default path is byte-identical rerun-safe.
    """

    started_at = clock.now()
    chosen_run_id = run_id or default_run_id()
    if trace_path is None:
        trace_path = (
            Path(out_root).parent / "logs" / "trace.jsonl"
            if out_root is not None
            else config.TRACE_PATH
        )
    trace = TraceWriter(trace_path, chosen_run_id)
    trace.emit(step=0, tool="run_start", source="code")
    store = Store(db_path)
    try:
        store.mark_running_as_aborted(except_run_id=chosen_run_id)
        previous_run_id, baseline_note = previous_baseline(store, chosen_run_id, profile.domain)
        store.start_run(chosen_run_id, url=profile.domain, started_at=started_at)

        audit: AuditSnapshot = run_audit(
            profile.base_url,
            max_pages=config.MAX_OWN_PAGES,
            fixture_path=fixture_path,
        )
        audit_fetches = 0 if fixture_path is not None else fetch_count()
        if fetch_budget_exhausted():
            trace.emit(step="budget", tool="audit_site", source="code",
                       status="error", kind="budget", reason="max_fetches")
        trace.emit(
            step=1,
            tool="audit_site",
            args={"url": profile.base_url, "max_pages": config.MAX_OWN_PAGES,
                  "fetches": audit_fetches},
            source="cache" if fixture_path is not None else "net",
        )
        keywords = build_keywords(profile)
        source_fetches = 0
        serp: list[SerpResult] = []
        competitor_pages: list[CompetitorPage] = []
        counts: dict[str, str | int] = {}
        query_pages: dict[str, list[str]] = {}
        if with_sources or with_scraping:
            mined_total: list[Keyword] = []
            counts = {
                "suggest": 0,
                "serp": 0,
                "gsc_csv": 0,
                "competitor_pages": 0,
                "suggest_empty": 0,
                "serp_empty": 0,
                "fetches": 0,
            }
            if with_sources:
                mined, file_counts = mine_file_sources(profile, store, trace)
                mined_total.extend(mined)
                counts.update(file_counts)
                query_pages, gsc_pages_status = mine_gsc_pages(store, trace)
                counts["gsc_pages"] = (
                    len(query_pages) if gsc_pages_status == "ok" else gsc_pages_status
                )
            if with_scraping:
                mined, serp, competitor_pages, scrape_counts = mine_scraping_sources(
                    profile, store, trace
                )
                mined_total.extend(mined)
                counts.update(scrape_counts)
            keywords = merge_keywords(keywords, mined_total)
            source_fetches = counts["fetches"] if isinstance(counts.get("fetches"), int) else 0
        clusters = build_clusters(keywords)
        trace.emit(step=2, tool="mine_keywords", args={"count": len(keywords)})

        gaps = analyze(
            audit,
            clusters,
            competitor_pages=competitor_pages,
            serp=serp,
            cities=profile.cities,
            query_page_map=query_pages or None,
            gsc_demand=gsc_demand_for(keywords),
        )
        backlog = build_backlog(
            gaps,
            money_keywords=money_keywords_for(profile),
            money_urls=profile.money_urls,
        )
        drafts: dict[str, str] = {}
        if with_drafts:
            drafts, rejected = write_drafts(backlog, profile, trace=trace, run_id=chosen_run_id)
            if rejected:
                trace.emit(step="drafts", tool="draft", args={"rejected": len(rejected)},
                           source="code", status="rejected", kind="compliance_reject")
        trace.emit(step=3, tool="analyze_gap", args={"gaps": len(gaps)})
        trace.emit(step=4, tool="build_backlog", args={"items": len(backlog)})

        save_run_stages(
            store,
            chosen_run_id,
            audit=audit,
            keywords=keywords,
            serp=serp,
            competitor_pages=competitor_pages,
            gaps=gaps,
            backlog=backlog,
        )
        store.finish_run(
            chosen_run_id,
            status="ok",
            site_score=audit.site_score,
            grade=audit.grade,
            llm_calls=0,
            tokens_in=0,
            tokens_out=0,
            finished_at=clock.now(),
        )

        generated_at = clock.now().isoformat(timespec="seconds")
        budgets = {
            "steps": 7,
            "fetches": source_fetches + audit_fetches,
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "mode": "no-llm",
            "drafts": len(drafts),
        }
        if with_sources or with_scraping:
            budgets["sources"] = counts
        _paths, markdown, diff = render_and_write_run(
            store,
            chosen_run_id,
            audit=audit,
            keywords=keywords,
            serp=serp,
            competitor_pages=competitor_pages,
            gaps=gaps,
            backlog=backlog,
            drafts=drafts,
            budgets=budgets,
            previous_run_id=previous_run_id,
            baseline_note=baseline_note,
            generated_at=generated_at,
            out_root=out_root,
        )
        trace.emit(
            step=5,
            tool="write_report",
            args={"backlog": len(backlog)},
            source="code",
        )
        trace.emit(
            step=6,
            tool="run_end",
            source="code",
            status="ok",
            site_score=audit.site_score,
            grade=audit.grade,
        )

        return RunReport(
            run_id=chosen_run_id,
            status="ok",
            site_score=audit.site_score,
            grade=audit.grade,
            generated_at=generated_at,
            report_markdown=markdown,
            backlog=backlog,
            diff=diff,
            budgets=budgets,
        )
    except Exception as exc:
        # A half-written run must not look successful. The next start marks it
        # aborted if this update itself fails.
        trace.emit(
            step="error",
            tool="run_end",
            source="code",
            status="error",
            kind="error",
            error_type=type(exc).__name__,
        )
        with contextlib.suppress(Exception):
            # shutdown must not mask the original error
            store.finish_run(
                chosen_run_id,
                status="aborted",
                site_score=0.0,
                grade="F",
                finished_at=clock.now(),
            )
        raise
    finally:
        store.close()


__all__ = [
    "build_clusters",
    "build_keywords",
    "default_run_id",
    "gsc_demand_for",
    "load_profile",
    "merge_keywords",
    "mine_file_sources",
    "mine_gsc_pages",
    "mine_scraping_sources",
    "money_keywords_for",
    "previous_baseline",
    "render_and_write_run",
    "run_deterministic",
    "save_run_stages",
]
