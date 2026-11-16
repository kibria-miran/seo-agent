"""UK financial-promotion compliance gate (section 8.6).

``check_text`` is pure code and never calls an LLM. It is a starting point,
not legal advice: confirm final wording with a compliance consultant or
network before publishing.

Rule map
--------
C1   banned absolutes, including claims loaded from evals/banned_claims.json
C1b  bare "no fees" without a fee-disclosure sentence in the same draft
C2   the word "free" without a fee-disclosure sentence
C3   mortgage content without the repossession risk warning
C4   missing FCA firm reference
C5   a rate/APR claim without a "representative example"
C6   invented testimonials, ratings, awards or lender partnerships
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from src import config


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str
    match: str = ""

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.rule}: {self.message}" + (f" ({self.match!r})" if self.match else "")


_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\ufeff]")
_APOSTROPHE_RE = re.compile(r"[\u2018\u2019\u02bc]")
_DASH_RE = re.compile(r"[\u2010-\u2015]")
_SPACE_RE = re.compile(r"\s+")
_NEGATORS = (
    "not ",
    "n't",
    "no ",
    "never ",
    "cannot",
    "can't",
    "won't",
    "without ",
    "do not",
    "does not",
    "isn't",
    "aren't",
)
_SENTENCE_BREAKS = (". ", "; ", "! ", "? ", "\n")


def normalise(text: str) -> str:
    """NFKC, zero-width stripped, lowercase, curly punctuation folded."""

    text = unicodedata.normalize("NFKC", text or "")
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _APOSTROPHE_RE.sub("'", text)
    text = _DASH_RE.sub("-", text)
    text = text.casefold()
    return _SPACE_RE.sub(" ", text).strip()


def _is_negated(text: str, position: int, window: int = 90) -> bool:
    """True if a negator appears in the same sentence before ``position``."""

    before = text[max(0, position - window) : position]
    cut = max(before.rfind(marker) for marker in _SENTENCE_BREAKS)
    if cut != -1:
        before = before[cut + len(". ") :]
    return any(negator in before for negator in _NEGATORS)


def _load_banned_claims(path=None) -> tuple[str, ...]:
    claims = list(config.BANNED_CLAIMS)
    target = path or config.BANNED_CLAIMS_PATH
    try:
        raw = json.loads(open(target, encoding="utf-8").read())
    except (OSError, ValueError, TypeError):
        return tuple(claims)
    if isinstance(raw, dict):
        raw = raw.get("banned_claims", raw.get("claims", []))
    if isinstance(raw, list):
        claims.extend(str(item) for item in raw if str(item).strip())
    # Stable de-duplication; casefolded because matching is case-insensitive.
    seen: set[str] = set()
    unique: list[str] = []
    for claim in claims:
        key = normalise(claim)
        if key and key not in seen:
            seen.add(key)
            unique.append(claim)
    return tuple(unique)


def _has_disclosure(text: str) -> bool:
    return any(normalise(phrase) in text for phrase in config.FREE_DISCLOSURE_PHRASES)


def _content_kind(page_kind: str) -> bool:
    return normalise(page_kind) in config.CONTENT_PAGE_KINDS


def check_text(
    text: str,
    page_kind: str = "content",
    *,
    fca_firm_ref: str | None = None,
    banned_claims_path=None,
) -> tuple[bool, list[Violation]]:
    """Return ``(ok, violations)`` for one public-facing piece of text."""

    text = normalise(text)
    violations: list[Violation] = []

    # C1 -- banned absolutes, negation-aware.
    for claim in _load_banned_claims(banned_claims_path):
        needle = normalise(claim)
        if not needle:
            continue
        for match in re.finditer(re.escape(needle), text):
            if not _is_negated(text, match.start()):
                violations.append(
                    Violation("C1", f"banned absolute claim: {claim!r}", match.group(0))
                )

    # C1b -- bare "no fees" needs a disclosure sentence in the same draft.
    no_fees_match = re.search(r"\bno fees?\b", text)
    if no_fees_match and not _has_disclosure(text):
        if not _is_negated(text, no_fees_match.start()):
            violations.append(
                Violation(
                    "C1b",
                    "'no fees' needs a fee-disclosure sentence in the same draft",
                    "no fees",
                )
            )

    # C2 -- "free" needs a disclosure sentence in the same draft.
    free_match = re.search(r"\bfree\b", text)
    if free_match and not _has_disclosure(text):
        violations.append(
            Violation(
                "C2",
                "'free' needs a fee-disclosure sentence in the same draft",
                free_match.group(0),
            )
        )

    # C3 -- repossession risk warning on mortgage content.
    if _content_kind(page_kind) and normalise(config.RISK_WARNING) not in text:
        violations.append(
            Violation("C3", "mortgage content is missing the repossession risk warning")
        )

    # C4 -- FCA firm reference on content.
    if _content_kind(page_kind):
        if fca_firm_ref:
            if fca_firm_ref not in text:
                violations.append(
                    Violation("C4", f"FCA firm reference {fca_firm_ref} is missing")
                )
        elif not (
            re.search(r"\b\d{6}\b", text)
            and re.search(r"\bfca\b|\bfirm reference\b|\bfinancial conduct authority\b", text)
        ):
            violations.append(
                Violation("C4", "FCA firm reference (6 digits) is missing")
            )

    # C5 -- rates/APR require a representative example.
    rate_match = re.search(config.RATE_PATTERN, text)
    if rate_match and config.REPRESENTATIVE_EXAMPLE not in text:
        violations.append(
            Violation(
                "C5",
                "rate/APR claim needs a 'representative example' block",
                rate_match.group(0),
            )
        )

    # C6 -- invented social proof / partnerships, negation-aware.
    for pattern in config.BANNED_SOCIAL_PROOF_PATTERNS:
        for match in re.finditer(pattern, text):
            if not _is_negated(text, match.start()):
                violations.append(
                    Violation("C6", "invented or unverifiable social proof", match.group(0))
                )

    return (not violations), violations


def check_many(
    texts: Iterable[str],
    page_kind: str = "content",
    *,
    fca_firm_ref: str | None = None,
) -> tuple[bool, list[Violation]]:
    """Check several fields with one shared disclosure context.

    The compliance rules operate on a draft as a whole, so joining fields is
    the correct behaviour for a title + meta + body combination.
    """

    joined = "\n\n".join(t for t in texts if t)
    return check_text(joined, page_kind, fca_firm_ref=fca_firm_ref)


__all__ = ["Violation", "check_many", "check_text", "normalise"]
