"""Markdown report, backlog JSON and draft writer (section 8.9, I-20).

All body numbers come from the database-backed models passed in; none come
from LLM prose. The body is timestamp-free. Only the header uses
``clock.now()`` (or an explicit ``generated_at``), so two renders from the same
state with the same injected clock are byte-identical.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from src import clock, config
from src.models import (
    AuditDiff,
    AuditSnapshot,
    BacklogItem,
    CompetitorPage,
    Gap,
    Keyword,
    SerpResult,
)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DRAFT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")
_EVIDENCE_LIMIT = 420


class ReportError(ValueError):
    """Raised for an unsafe run id, draft name or output path."""


def _host(url: str) -> str:
    return urlparse(url).hostname or url


def _generated(generated_at: str | None) -> str:
    if generated_at:
        return generated_at
    return clock.now().isoformat(timespec="seconds")


def _evidence(evidence: Mapping[str, Any]) -> str:
    rendered = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))
    if len(rendered) > _EVIDENCE_LIMIT:
        rendered = rendered[: _EVIDENCE_LIMIT - 1] + "\u2026"
    return rendered


def _status_line(run: Mapping[str, Any], generated_at: str | None) -> str:
    return (
        f"_Run `{run.get('run_id', '')}` \u00b7 generated {_generated(generated_at)} "
        f"\u00b7 status {run.get('status', 'unknown')}_"
    )


def _scorecard(
    audit: AuditSnapshot,
    run: Mapping[str, Any],
    diff: AuditDiff | None,
    previous_run_id: str | None,
    keywords: Sequence[Keyword],
    gaps: Sequence[Gap],
) -> list[str]:
    if previous_run_id:
        delta = f"{diff.score_delta:+.1f}" if diff else "n/a"
    else:
        delta = "n/a (first run)"
    counts = {
        "CRITICAL": sum(1 for issue in audit.issues if issue.severity.value == "CRITICAL"),
        "WARNING": sum(1 for issue in audit.issues if issue.severity.value == "WARNING"),
        "INFO": sum(1 for issue in audit.issues if issue.severity.value == "INFO"),
    }
    return [
        "## Scorecard",
        "",
        f"- Site score: **{audit.site_score:.1f}** ({audit.grade})",
        f"- Delta vs previous run: {delta}",
        f"- Pages crawled: {audit.pages_crawled}",
        f"- Issues: {len(audit.issues)} total \u00b7 "
        f"{counts['CRITICAL']} critical \u00b7 {counts['WARNING']} warning \u00b7 "
        f"{counts['INFO']} info",
        f"- Keywords mined: {len(keywords)}",
        f"- Gaps open: {len(gaps)}",
        f"- Backlog items: {run.get('backlog_count', 'n/a')}",
        "",
    ]


def _backlog_section(backlog: Sequence[BacklogItem], limit: int = 10) -> list[str]:
    lines = ["## Top backlog", ""]
    if not backlog:
        lines.extend(["_No backlog items produced._", ""])
        return lines
    shown = list(backlog[:limit])
    lines.append(f"Showing {len(shown)} of {len(backlog)} items, highest priority first.")
    lines.append("")
    for item in shown:
        lines.append(
            f"{item.item_id}. **{item.title or item.kind}**  "
            f"\n   - priority `{item.priority:.4f}` \u00b7 impact {item.impact} \u00b7 "
            f"confidence {item.confidence:.2f} \u00b7 effort {item.effort}"
            f"\n   - kind `{item.kind}` \u00b7 target `{item.target}` \u00b7 status `{item.status}`"
            f"\n   - evidence: `{_evidence(item.evidence)}`"
        )
    lines.append("")
    return lines


def _gap_lines(title: str, values: Sequence[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if not values:
        lines.extend(["_None._", ""])
        return lines
    lines.extend(f"- {value}" for value in values)
    lines.append("")
    return lines


def _open_gap_lines(gaps: Sequence[Gap]) -> list[str]:
    lines = ["## Open gaps", ""]
    if not gaps:
        lines.extend(["_None._", ""])
        return lines
    for gap in gaps:
        sources = ", ".join(sorted(set(gap.sources))) or "audit"
        lines.append(
            f"- `{gap.gap_type.value}` **{gap.keyword}** \u00b7 target `{gap.target or 'n/a'}` "
            f"\u00b7 sources: {sources}"
        )
    lines.append("")
    return lines


def _competitor_section(pages: Sequence[CompetitorPage]) -> list[str]:
    lines = ["## Competitor coverage", ""]
    if not pages:
        lines.extend(["_No competitor pages parsed._", ""])
        return lines
    grouped: dict[str, list[CompetitorPage]] = {}
    for page in pages:
        grouped.setdefault(page.domain, []).append(page)
    for domain in sorted(grouped):
        entries = sorted(grouped[domain], key=lambda page: page.url)
        schemas = sorted({schema for page in entries for schema in page.schema_types})
        example = entries[0].title or entries[0].url
        lines.append(
            f"- **{domain}**: {len(entries)} page(s) \u00b7 "
            f"schema: {', '.join(schemas) if schemas else 'none'} \u00b7 example: \"{example}\""
        )
    lines.append("")
    return lines


def _drafts_section(drafts: Sequence[str]) -> list[str]:
    lines = ["## Drafts", ""]
    if not drafts:
        lines.extend(["_No drafts written this run._", ""])
        return lines
    lines.extend(f"- `{name}`" for name in sorted(drafts))
    lines.append("")
    return lines


def _budget_section(run: Mapping[str, Any], budgets: Mapping[str, Any]) -> list[str]:
    llm_calls = budgets.get("llm_calls", run.get("llm_calls", 0))
    tokens_in = budgets.get("tokens_in", run.get("tokens_in", 0))
    tokens_out = budgets.get("tokens_out", run.get("tokens_out", 0))
    fetches = budgets.get("fetches", 0)
    steps = budgets.get("steps", 0)
    return [
        "## Run budgets",
        "",
        f"- Status: `{run.get('status', 'unknown')}`",
        f"- Steps: {steps} / {config.MAX_STEPS}",
        f"- LLM calls: {llm_calls} / {config.MAX_LLM_CALLS}",
        f"- Tokens: {tokens_in} in / {tokens_out} out "
        f"(caps {config.MAX_TOKENS_IN} / {config.MAX_TOKENS_OUT})",
        f"- Fetches: {fetches} / {config.MAX_FETCHES}",
        f"- LLM wall-clock cap: {config.MAX_LLM_SECONDS}s \u00b7 run cap: {config.MAX_RUN_SECONDS}s",
        "",
    ]


def render_report(
    run: Mapping[str, Any],
    audit: AuditSnapshot,
    *,
    diff: AuditDiff | None = None,
    backlog: Sequence[BacklogItem] = (),
    gaps: Sequence[Gap] = (),
    keywords: Sequence[Keyword] = (),
    serp: Sequence[SerpResult] = (),
    competitor_pages: Sequence[CompetitorPage] = (),
    drafts: Sequence[str] = (),
    budgets: Mapping[str, Any] | None = None,
    previous_run_id: str | None = None,
    generated_at: str | None = None,
) -> str:
    """Render the full report. Body is timestamp-free; header is not."""

    host = _host(str(run.get("url") or audit.url))
    lines: list[str] = [
        f"# SEO growth report \u2014 {host}",
        "",
        _status_line(run, generated_at),
        "",
    ]
    lines.extend(_scorecard(audit, run, diff, previous_run_id, keywords, gaps))

    if diff is not None:
        lines.extend(_gap_lines("New issues since previous run", diff.new_items))
        lines.extend(_gap_lines("Issues closed since previous run", diff.closed_items))
        lines.extend(_gap_lines("New gaps since previous run", diff.new_gaps))
        lines.extend(_gap_lines("Gaps closed since previous run", diff.closed_gaps))
    else:
        lines.extend(_gap_lines("New issues since previous run", []))
        lines.extend(_gap_lines("Issues closed since previous run", []))
        lines.extend(_gap_lines("New gaps since previous run", []))
        lines.extend(_gap_lines("Gaps closed since previous run", []))

    lines.extend(_open_gap_lines(gaps))
    lines.extend(_backlog_section(backlog, limit=10))
    lines.extend(_competitor_section(competitor_pages))
    if serp:
        lines.extend(["## SERP evidence", ""])
        lines.extend(
            f"- `{result.query}` #{result.rank} \u00b7 {result.domain} \u00b7 {result.url}"
            for result in sorted(serp, key=lambda item: (item.query, item.rank, item.url))
        )
        lines.append("")
    else:
        lines.extend(["## SERP evidence", "", "_No SERP results this run._", ""])

    lines.extend(_drafts_section(drafts))
    lines.extend(_budget_section(run, budgets or {}))
    return "\n".join(lines).rstrip() + "\n"


def render_backlog_json(backlog: Sequence[BacklogItem]) -> str:
    payload = [item.model_dump(mode="json") for item in backlog]
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _safe_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.match(run_id) or run_id in {".", ".."}:
        raise ReportError(f"unsafe run_id: {run_id!r}")
    return run_id


def _safe_draft_name(name: str) -> str:
    if not _DRAFT_NAME_RE.match(name):
        raise ReportError(f"unsafe draft name (expected a flat *.md name): {name!r}")
    return name


def write_report(
    run_id: str,
    markdown: str,
    backlog: Sequence[BacklogItem],
    *,
    drafts: Mapping[str, str] | None = None,
    out_root: str | Path | None = None,
) -> dict[str, Path]:
    """Write ``report.md``, ``backlog.json`` and flat ``drafts/*.md`` files.

    All writes stay under ``out_root/<run_id>/``; unsafe ids/names are rejected
    before any filesystem call (D-15).
    """

    safe_id = _safe_run_id(run_id)
    root = Path(out_root) if out_root is not None else config.OUT_DIR
    target = (root / safe_id).resolve()
    root_resolved = root.resolve()
    if not target.is_relative_to(root_resolved):
        raise ReportError(f"run output escapes out_root: {target}")

    target.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    report_path = target / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    paths["report"] = report_path

    backlog_path = target / "backlog.json"
    backlog_path.write_text(render_backlog_json(backlog), encoding="utf-8")
    paths["backlog"] = backlog_path

    if drafts:
        draft_dir = target / "drafts"
        draft_dir.mkdir(exist_ok=True)
        for name in sorted(drafts):
            safe_name = _safe_draft_name(name)
            draft_path = draft_dir / safe_name
            draft_path.write_text(drafts[name], encoding="utf-8")
            paths[f"draft:{safe_name}"] = draft_path

    return paths


__all__ = [
    "ReportError",
    "render_backlog_json",
    "render_report",
    "write_report",
]
