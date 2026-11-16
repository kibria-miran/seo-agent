"""Google Search Console CSV export source (D-3).

GSC's "Queries.csv" export is a plain CSV, so the source reads a local file
or the path in ``SEO_AGENT_GSC_CSV`` — no network and no credentials needed.

- unset and no path passed  -> skipped, logged as ``dep_unmet`` (D-14);
- configured but missing    -> ``SourceError`` (a broken setup is an error,
                               not a silent skip).

Rows are parsed defensively: headers are matched case-insensitively, numbers
tolerate thousands separators and percent signs, and rows without a query are
dropped. Keywords with impressions but little evidence of coverage are the
highest-value demand signal this tool gets, so every parsed query is kept.
"""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.keywords import city_in, intent_for, normalise
from src.models import Keyword
from src.sources.base import Source, SourceError
from src.store import Store
from src.trace import TraceWriter

ENV_VAR = "SEO_AGENT_GSC_CSV"

_QUERY_KEYS = ("top queries", "query", "queries", "search query")
_CLICKS_KEYS = ("clicks",)
_IMPRESSIONS_KEYS = ("impressions",)
_CTR_KEYS = ("ctr",)
_POSITION_KEYS = ("position", "avg position", "average position")

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


class GscCsvSource(Source):
    """Parse a GSC query-performance CSV export into keyword demand."""

    name = "gsc_csv"

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
            raise SourceError(f"GSC CSV not found at {raw} (set {ENV_VAR})")
        return raw

    def collect(
        self,
        query: str = "queries",
        *,
        store: Store,
        trace: TraceWriter | None = None,
        fetch: Any | None = None,
        ttl_seconds: int | None = None,
    ):
        del query  # cache key is the file fingerprint, not the argument
        # Cache key includes the export's size and mtime so a fresh CSV never
        # serves stale rows within the TTL window.
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
            raise SourceError(f"cannot read GSC CSV {path}: {exc}") from exc
        rows = list(csv.DictReader(text.splitlines()))
        mapping = _header_map(rows[0].keys() if rows else [])
        query_col = _first(mapping, _QUERY_KEYS)
        if query_col is None:
            raise SourceError(
                f"GSC CSV {path} has no query column; expected one of {_QUERY_KEYS}"
            )
        clicks_col = _first(mapping, _CLICKS_KEYS)
        impressions_col = _first(mapping, _IMPRESSIONS_KEYS)
        ctr_col = _first(mapping, _CTR_KEYS)
        position_col = _first(mapping, _POSITION_KEYS)

        best: dict[str, dict[str, Any]] = {}
        for row in rows:
            keyword = normalise(str(row.get(query_col, "")))
            if not keyword:
                continue
            clicks = _number(row.get(clicks_col)) if clicks_col else None
            impressions = _number(row.get(impressions_col)) if impressions_col else None
            ctr = _number(row.get(ctr_col)) if ctr_col else None
            position = _number(row.get(position_col)) if position_col else None
            entry = best.get(keyword)
            impressions = impressions or 0.0
            if entry is None or impressions > entry["impressions"]:
                best[keyword] = {
                    "keyword": keyword,
                    "clicks": clicks or 0.0,
                    "impressions": impressions,
                    "ctr": ctr,
                    "position": position,
                }
        return [best[key] for key in sorted(best)]

    @staticmethod
    def to_keywords(
        items: Sequence[Mapping[str, Any]], *, cities: Sequence[str] = ()
    ) -> list[Keyword]:
        city_list = tuple(cities)
        keywords = []
        for item in items:
            keyword = normalise(str(item.get("keyword", "")))
            if not keyword:
                continue

            def _metric(name: str) -> float | None:
                value = item.get(name)
                if value is None:
                    return None
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            keywords.append(
                Keyword(
                    keyword=keyword,
                    source="gsc_csv",
                    intent=intent_for(keyword, city_list),
                    city=city_in(keyword, city_list),
                    gsc_clicks=_metric("clicks"),
                    gsc_impressions=_metric("impressions"),
                    gsc_ctr=_metric("ctr"),
                    gsc_position=_metric("position"),
                )
            )
        return keywords


__all__ = ["ENV_VAR", "GscCsvSource"]
