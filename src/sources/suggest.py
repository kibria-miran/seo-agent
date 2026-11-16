"""Keyless autocomplete source (Google Suggest, D-3).

``GET https://suggestqueries.google.com/complete/search?client=firefox&q=…``
returns ``[query, [suggestion, …]]`` as JSON. Suggestions are untrusted
text: each is normalised and injection-scanned by the shared scrub in
``src.sources.base.Source.collect`` before being cached.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from src import config
from src.keywords import city_in, intent_for, normalise
from src.models import Keyword
from src.sources import fetch
from src.sources.base import Source, SourceError

SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
MAX_SUGGESTIONS_PER_SEED = 10


class SuggestSource(Source):
    """Expand seed terms into autocomplete candidates."""

    name = "suggest"

    def fetch(self, query: str) -> Sequence[Mapping[str, Any]]:
        params = urlencode({"client": "firefox", "q": query, "hl": "en-GB"})
        try:
            body = fetch.http_get(f"{SUGGEST_URL}?{params}")
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except (fetch.FetchError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceError(f"suggest failed for {query!r}: {exc}") from exc
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
            raise SourceError(f"suggest returned an unexpected payload for {query!r}")
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for raw in payload[1]:
            value = normalise(str(raw))
            if not value or value == normalise(query) or value in seen:
                continue
            seen.add(value)
            items.append({"keyword": value})
            if len(items) >= MAX_SUGGESTIONS_PER_SEED:
                break
        return items

    @staticmethod
    def to_keywords(items: Sequence[Mapping[str, Any]], *, cities: Sequence[str] = ()) -> list[Keyword]:
        city_list = tuple(cities)
        keywords = []
        for item in items:
            keyword = normalise(str(item.get("keyword", "")))
            if not keyword:
                continue
            keywords.append(
                Keyword(
                    keyword=keyword,
                    source="suggest",
                    intent=intent_for(keyword, city_list),
                    city=city_in(keyword, city_list),
                )
            )
        return keywords


def seed_terms(profile: Any) -> list[str]:
    """Seeds for expansion: money-page keywords + target keywords."""

    from src.pipeline import money_keywords_for  # local import avoids a cycle

    seeds = {normalise(kw) for kw in profile.target_keywords if normalise(kw)}
    seeds.update(money_keywords_for(profile))
    return sorted(seeds)[: config.MAX_SUGGEST]


__all__ = ["SUGGEST_URL", "SuggestSource", "seed_terms"]
