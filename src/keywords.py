"""Keyword normalisation, stemming and coverage (pure code, section 8.3).

The LLM may label clusters, but membership and coverage are decided here.
Everything in this module is deterministic: same input, same output.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from src import config
from src.models import Cluster, Keyword, PageData

_PUNCT_RE = re.compile(r"[^a-z0-9\s]+")
_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STEM_MAP = {
    "remortgage": "remortgage",
    "remortgages": "remortgage",
    "remortgaging": "remortgage",
    "mortgage": "mortgage",
    "mortgages": "mortgage",
    "mortgaging": "mortgage",
    "adviser": "adviser",
    "advisor": "adviser",
    "advisers": "adviser",
    "advisors": "adviser",
    "buy": "buy",
    "buying": "buy",
    "buyer": "buyer",
    "buyers": "buyer",
    "let": "let",
    "letting": "let",
    "landlord": "landlord",
    "landlords": "landlord",
    "fee": "fee",
    "fees": "fee",
}


def normalise(keyword: str) -> str:
    """NFKC, lowercase, collapse whitespace, strip punctuation."""

    text = unicodedata.normalize("NFKC", keyword).casefold()
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    # UK mortgage copy writes both "re-mortgage" and "remortgage".
    return text.replace("re mortgage", "remortgage")


def stem_token(token: str) -> str:
    """Small, explicit UK-mortgage stemmer.

    It is intentionally not a linguistic stemmer: we only need the handful of
    variants that appear in titles and H1s.
    """

    token = normalise(token)
    if not token:
        return ""
    return _STEM_MAP.get(token, token)


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalise(text))


def precheck_terms(text: str) -> set[str]:
    """Significant stemmed tokens for the N-5 NO_PAGE pre-check (N-15)."""

    return {
        stem_token(token)
        for token in tokens(text)
        if token not in config.PRECHECK_STOPLIST and len(token) > 1
    }


def precheck_field_tokens(page: PageData) -> dict[str, set[str]]:
    """Per-field (title/H1/H2) raw+stemmed token sets for the pre-check."""

    fields = {
        "title": page.title or "",
        "h1": " ".join(page.h1_tags),
        "h2": " ".join(page.h2_tags),
    }
    out: dict[str, set[str]] = {}
    for name, text in fields.items():
        raw = tokens(text)
        out[name] = set(raw) | {stem_token(t) for t in raw}
    return out


def head_terms(text: str) -> set[str]:
    """Significant stemmed tokens, with the stoplist removed."""

    return {
        stem_token(token)
        for token in tokens(text)
        if token not in config.UK_MORTGAGE_STOPLIST and len(token) > 1
    }


def stemmed_text(text: str) -> str:
    return " ".join(stem_token(token) for token in tokens(text))


def head_covered(head_term: str, text: str) -> bool:
    """True when ``text`` contains every significant token of ``head_term``."""

    wanted = head_terms(head_term)
    if not wanted:
        return False
    haystack = set(tokens(text)) | set(tokens(stemmed_text(text)))
    # Check both raw and stemmed forms so "re-mortgage" matches "remortgage".
    normalised = normalise(text)
    if all(term in normalised for term in wanted):
        return True
    return wanted.issubset(haystack)


def page_covers(head_term: str, page: PageData) -> bool:
    """Coverage rule: page title OR H1 contains the cluster head term."""

    haystack = " ".join(
        part
        for part in (
            page.title or "",
            " ".join(page.h1_tags),
        )
        if part
    )
    return head_covered(head_term, haystack)


def cluster_covered(cluster: Cluster, pages: list[PageData]) -> bool:
    return any(page_covers(cluster.head_term, page) for page in pages)


def intent_for(keyword: str, cities: tuple[str, ...] | None = None) -> str:
    """Rule-based intent, local first, then transactional, then informational."""

    text = normalise(keyword)
    city_values = cities or config.UK_CITIES
    if config.LOCAL_NEAR_ME in text:
        return "local"
    if any(config.canonical_city(city) and config.canonical_city(city).casefold() in text for city in city_values):
        return "local"
    if any(token in text for token in config.TRANSACTIONAL_TOKENS):
        return "transactional"
    if any(token in text for token in config.INFORMATIONAL_TOKENS):
        return "informational"
    return "informational"


def city_in(keyword: str, cities: tuple[str, ...] | None = None) -> str | None:
    """Return the first canonical city mentioned in the keyword, if any."""

    text = normalise(keyword)
    for city in cities or config.UK_CITIES:
        if normalise(city) in text:
            return city
    return None


def jaccard(left: str, right: str) -> float:
    a, b = set(tokens(left)), set(tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster(
    keywords: Sequence[Keyword] | Sequence[str],
    threshold: float | None = None,
) -> list[Cluster]:
    """Deterministic token-set clustering.

    Two keywords join when their Jaccard similarity is at least the threshold
    AND they share a significant (non-stoplist) token. The head term is the
    shortest member, then alphabetical. Cluster ids are assigned after sorting,
    so input order never changes the result. The LLM may label a cluster; it
    may not assign membership (D-2).
    """

    limit = config.JACCARD_THRESHOLD if threshold is None else float(threshold)
    values = sorted(
        {
            item.keyword if isinstance(item, Keyword) else normalise(str(item))
            for item in keywords
        }
    )
    values = [value for value in values if value]
    parent = list(range(len(values)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if not (head_terms(values[i]) & head_terms(values[j])):
                continue
            if jaccard(values[i], values[j]) >= limit:
                union(i, j)

    groups: dict[int, list[str]] = {}
    for index, value in enumerate(values):
        groups.setdefault(find(index), []).append(value)

    rows: list[tuple[str, list[str]]] = []
    for members in groups.values():
        head = min(members, key=lambda item: (len(item.split()), len(item), item))
        rows.append((head, sorted(members)))
    rows.sort(key=lambda row: (row[0], row[1]))

    return [
        Cluster(
            cluster_id=f"c{index:02d}",
            label=head.title(),
            head_term=head,
            keywords=members,
        )
        for index, (head, members) in enumerate(rows, start=1)
    ]
