"""Query-to-page mapping from a user-supplied GSC CSV export.

The Search Console UI exports queries and pages as separate reports; neither
contains the query -> page cross-tab. To attribute demand to pages without
the paid API or OAuth setup, this source reads a small, hand-prepared CSV
with at least ``query`` and ``page`` columns (produced either by filtering
GSC by page and exporting the queries for each top page, or from the
free ``searchAnalytics.query`` Search Console API with dimensions
``query,page``). It is opt-in; unset means dep_unmet and skipped (D-14).

Rows are parsed defensively: headers are matched case-insensitively and
numeric columns are tolerated (thousands separators, % signs). One row per
``query | page`` pair is kept; duplicates are de-duplicated.
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.keywords import normalise
from src.sources.base import Source, SourceError
from src.store import Store
from src.trace import TraceWriter

ENV_VAR = "SEO_AGENT_GSC_PAGES_CSV"

_QUERY_KEYS = ("query", "queries", "top queries", "search query")
_PAGE_KEYS = ("page", "pages", "top pages", "url", "landing page")
_NUMERIC_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _header_map(fieldnames: Sequence[str] | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in fieldnames or []:
        cleaned = " ".join(str(name).strip().casefold().replace("_", " ").split())
        mapping[cleaned] = name
    return mapping


def _first(mapping: Mapping[str, str], keys: Sequence[str]) -> str | None:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _number(value: str | None) -> float | None:
    if not value:
        return None
    match = _NUMERIC_RE.search(value.replace(",", "").replace("%", ""))
    return float(match.group(0)) if match else None


class GscPagesSource(Source):
    """Map queries to the page that earned their impressions/clicks."""

    name = "gsc_pages"

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None

    def requirements_met(self) -> tuple[bool, str]:
        if self._path is not None:
            return True, ""
        if os.environ.get(ENV_VAR):
            return True, ""
        return False, f"dep_unmet: {ENV_VAR}"

    @property
    def csv_path(self) -> Path:
        raw = self._path or Path(os.environ.get(ENV_VAR, ""))
        if not raw.exists():
            raise SourceError(f"GSC pages CSV not found at {raw} (set {ENV_VAR})")
        return raw

    def collect(
        self,
        query: str = "pages",
        *,
        store: Store,
        trace: TraceWriter | None = None,
        fetch: Any | None = None,
        ttl_seconds: int | None = None,
    ):
        del query  # cache key is the file fingerprint, not the argument
        stat = self.csv_path.stat()  # raises SourceError if missing
        cache_query = f"{self.csv_path.name}:{stat.st_size}:{int(stat.st_mtime)}"
        return super().collect(
            cache_query, store=store, trace=trace, fetch=fetch, ttl_seconds=ttl_seconds
        )

    def fetch(self, query: str = "") -> Sequence[Mapping[str, Any]]:
        path = self.csv_path
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise SourceError(f"cannot read GSC pages CSV {path}: {exc}") from exc
        rows = list(csv.DictReader(text.splitlines()))
        mapping = _header_map(rows[0].keys() if rows else [])
        query_col = _first(mapping, _QUERY_KEYS)
        page_col = _first(mapping, _PAGE_KEYS)
        if query_col is None:
            raise SourceError(f"GSC pages CSV {path} has no query column; expected {_QUERY_KEYS}")
        if page_col is None:
            raise SourceError(f"GSC pages CSV {path} has no page column; expected {_PAGE_KEYS}")
        impressions_col = _first(mapping, ("impressions",))
        clicks_col = _first(mapping, ("clicks",))

        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            query = normalise(str(row.get(query_col, "")))
            page = str(row.get(page_col, "")).strip()
            if not query or not page:
                continue
            if page.startswith("/"):
                page = page  # root-relative export is used as-is
            key = (query, page)
            impressions = _number(row.get(impressions_col)) if impressions_col else None
            clicks = _number(row.get(clicks_col)) if clicks_col else None
            impressions = impressions or 0.0
            entry = pairs.get(key)
            if entry is None or impressions > entry["impressions"]:
                pairs[key] = {
                    "query": query,
                    "page": page,
                    "impressions": impressions,
                    "clicks": clicks or 0.0,
                }
        return [pairs[key] for key in sorted(pairs)]

    @staticmethod
    def to_query_page_map(items: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
        mapping: dict[str, set[str]] = {}
        for item in items:
            query = normalise(str(item.get("query", "")))
            page = str(item.get("page", "")).strip()
            if not query or not page:
                continue
            mapping.setdefault(query, set()).add(page)
        return {query: sorted(pages) for query, pages in sorted(mapping.items())}


__all__ = ["ENV_VAR", "GscPagesSource"]
