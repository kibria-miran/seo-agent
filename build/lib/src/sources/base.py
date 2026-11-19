"""One Source interface for every keyless data source (D-3, D-4, D-9, D-14).

A source does four things, always in this order:

1. check its declared requirements; an unmet requirement is *skipped* and
   logged as ``dep_unmet`` — it never raises into the pipeline (D-14);
2. serve from the TTL cache when fresh (``source|query`` key, I-3);
3. otherwise fetch, throttle happens in ``src.sources.fetch.http_get``;
4. drop any item whose text carries an injection marker, logging
   ``injection_attempt`` — fetched text is untrusted data (D-4).

Sources return plain JSON-serialisable dicts so cached payloads round-trip
byte-identically. Conversion into our Pydantic models happens in each
source's ``to_<model>`` helpers, never inside the cache.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src import config
from src.security import find_injection
from src.store import Store, cache_key
from src.trace import TraceWriter

# String keys whose values are untrusted page/SERP text. Everything else is
# structural metadata (rank, counts) and needs no scanning.
_TEXT_KEYS = ("keyword", "title", "snippet", "text")


class SourceError(RuntimeError):
    """A source could not produce data (transport failure, bad payload)."""


@dataclass(frozen=True)
class SourceResult:
    """Outcome of one ``collect`` call; ``skipped`` means dep_unmet."""

    source: str
    query: str
    items: tuple[dict[str, Any], ...] = ()
    from_cache: bool = False
    skipped: bool = False
    reason: str = ""


class Source(ABC):
    """Base class: cache + throttle + injection scrub + trace logging."""

    name: str = ""
    ttl_seconds: int = config.CACHE_TTL_SECONDS
    # Names of environment variables that must be set for this source to run.
    requires: tuple[str, ...] = ()

    def requirements_met(self) -> tuple[bool, str]:
        missing = [name for name in self.requires if not os.environ.get(name)]
        if missing:
            return False, "dep_unmet: " + ", ".join(missing)
        return True, ""

    def collect(
        self,
        query: str,
        *,
        store: Store,
        trace: TraceWriter | None = None,
        fetch: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
        ttl_seconds: int | None = None,
    ) -> SourceResult:
        if not self.name:  # pragma: no cover - guards subclass mistakes
            raise SourceError("Source subclasses must set ``name``")

        met, reason = self.requirements_met()
        if not met:
            self._emit(trace, query=query, source="code", status="skipped",
                       kind="dep_unmet", reason=reason)
            return SourceResult(source=self.name, query=query, skipped=True, reason=reason)

        key = cache_key(self.name, query)
        cached = store.get_cache(key)
        if cached is not None:
            items = tuple(dict(item) for item in cached)
            self._emit(trace, query=query, source="cache", status="ok")
            return SourceResult(source=self.name, query=query, items=items, from_cache=True)

        raw = list((fetch or self.fetch)(query))
        clean, dropped = self._scrub(raw)
        if not clean:
            if raw:
                # Items arrived but every one was dropped; or parser saw blocks and yielded nothing.
                self._emit(trace, query=query, source="net", status="ok",
                           kind="source_empty", dropped=dropped)
            else:
                self._emit(trace, query=query, source="net", status="ok",
                           kind="source_empty", dropped=0)
        if dropped:
            self._emit(trace, query=query, source="net", status="ok",
                       kind="injection_attempt", dropped=dropped)
        store.set_cache(
            key,
            list(clean),
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.ttl_seconds,
        )
        self._emit(trace, query=query, source="net", status="ok",
                   items=len(clean))
        return SourceResult(source=self.name, query=query, items=tuple(clean))

    @abstractmethod
    def fetch(self, query: str) -> Sequence[Mapping[str, Any]]:
        """Fetch raw items for ``query``. Never called on a cache hit."""

    # -- internals ---------------------------------------------------------

    def _scrub(
        self, items: Sequence[Mapping[str, Any]]
    ) -> tuple[tuple[dict[str, Any], ...], int]:
        clean: list[dict[str, Any]] = []
        dropped = 0
        for item in items:
            hit = False
            for text_key in _TEXT_KEYS:
                value = item.get(text_key)
                if isinstance(value, str) and find_injection(value):
                    hit = True
                    break
            if hit:
                dropped += 1
                continue
            clean.append(dict(item))
        return tuple(clean), dropped

    def _emit(
        self,
        trace: TraceWriter | None,
        *,
        query: str,
        source: str,
        status: str,
        kind: str = "action",
        **extra: Any,
    ) -> None:
        if trace is None:
            return
        # The query may contain terms a user would rather not see in logs;
        # TraceWriter stores a hash, never the raw string.
        trace.emit(step="sources", tool=self.name, args={"query": query},
                   source=source, status=status, kind=kind, **extra)


__all__ = [
    "Source",
    "SourceError",
    "SourceResult",
]
