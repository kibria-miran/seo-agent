"""Phase 7: compliance-linted draft generation (D-6, D-7).

Drafts are files for a human editor — the tool never publishes (D-7). Two
generation paths exist, both behind one function:

* ``--no-llm --with-drafts``: a deterministic skeleton with every mandatory UK
  mortgage disclosure baked in. Byte-stable for the same run/fixture/clock
  (D-12).
* ``--agent --with-drafts``: the LLM proposes copy, and the compliance lint
  (C1–C6) decides whether it may be written (D-2, D-6). One retry with the
  violations fed back, then the item is rejected and logged — the draft is
  never written to disk without passing the lint.

The lint is pattern matching, not a compliance review: it routinely misses
things a qualified adviser would catch. Passing it does not make copy
compliant; it only means no banned pattern was found. A qualified adviser
must review every draft before anything is published.

Nothing here is written before the lint clears it, in either mode.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from src.compliance import Violation, check_text
from src.models import BacklogItem, SiteProfile
from src.trace import TraceWriter

DRAFTABLE_KINDS = frozenset({"create_page", "create_local_page"})
MAX_DRAFTS = 3

_WORD_TARGET = 650
_SLUG_RE = re.compile(r"[^a-z0-9]+")

DRAFT_SYSTEM = """\
You write UK mortgage landing-page copy. Hard rules:
- Never say anything implies guaranteed approval, unlimited borrowing or
  the "best" or "lowest" rates.
- Include this exact risk sentence verbatim, once, near the end:
  "Your home may be repossessed if you do not keep up repayments on your mortgage."
- Include this exact FCA sentence verbatim, once:
  "{FIRMWARE} is authorised and regulated by the Financial Conduct Authority. FCA firm reference {FCA}."
- Include this exact fee sentence verbatim, once:
  "We do not charge a fee for our initial consultation."
- Never mention a specific rate, APR or percentage; do not include a
  representative example (none may exist yet).
- No invented reviews, ratings, awards, customer counts or partnerships.
- UK spelling. Plain text with markdown headings. About {WORDS} words.
- End with a clear call to book a free initial consultation.
"""


def draft_slug(target: str) -> str:
    slug = _SLUG_RE.sub("-", (target or "").casefold()).strip("-")
    return f"{slug or 'draft'}.md"


def template_draft(item: BacklogItem, profile: SiteProfile) -> str:
    """Deterministic, disclosure-complete skeleton for the human editor."""

    phrase = (item.title or item.target or item.item_id).replace("_", " ").strip()
    keyword = _head_keyword(item)
    city = str(item.evidence.get("city") or "").strip()
    # Do not repeat the city name when the keyword already carries it.
    location = ""
    if city and city.casefold() not in keyword.casefold():
        location = f" in {city}"
    return f"""# {phrase}

> THIS DRAFT HAS NOT BEEN REVIEWED. A qualified adviser must review and
> approve it before publication; the automated checks that produced it are a
> lint and not a promise of compliance, and it is not legal, financial
> or tax advice.

## {keyword.capitalize()}{location}

{profile.domain.replace("https://", "")} helps UK borrowers compare mortgage
options{location}. Every application is different: we look at your income,
existing commitments, credit history and deposit before recommending a lender.

## What to expect

- A conversation about your situation, your plans and your budget.
- A comparison of lender criteria, not just headline rates.
- Clear paperwork: what we need from you, and what happens next.

We do not charge a fee for our initial consultation.

## Why people come to us

Between you and a lender sits a lot of small print. Our advisers are trained
to read it so you do not have to, and to tell you when a deal is wrong for
you even if it is popular.

{_profile_entity(profile)} is authorised and regulated by the Financial
Conduct Authority. FCA firm reference {profile.fca_firm_ref}.

Your home may be repossessed if you do not keep up repayments on your mortgage.

## Next step

Book a free initial consultation. Bring your payslips or SA302s, your last
three months of bank statements, and your deposit evidence, and we will tell
you what is realistic before you commit to anything.
"""


def llm_draft_messages(
    item: BacklogItem,
    profile: SiteProfile,
    *,
    feedback: Sequence[Violation] | None = None,
) -> list[dict[str, str]]:
    system = DRAFT_SYSTEM.format(
        FIRMWARE=_profile_entity(profile),
        FCA=profile.fca_firm_ref,
        WORDS=_WORD_TARGET,
    )
    user = (
        f"Backlog item {item.item_id} ({item.kind}), target {item.target}.\n"
        f"Evidence: {item.evidence}.\n"
        f"Write the landing page copy now."
    )
    if feedback:
        problems = "; ".join(f"{violation.rule}: {violation.message}" for violation in feedback)
        user += f"\nThe previous draft failed compliance review: {problems}. Fix it."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _llm_draft(item: BacklogItem, profile: SiteProfile, llm: Any) -> tuple[str | None, int]:
    """Returns (text, attempts_used). Text is None if the gate rejects twice."""

    feedback: list[Violation] | None = None
    for attempt in (1, 2):
        raw = llm(llm_draft_messages(item, profile, feedback=feedback))
        text = str(raw).strip()
        ok, violations = check_text(text, "draft", fca_firm_ref=profile.fca_firm_ref)
        if ok:
            return text, attempt
        feedback = violations
    return None, 2


def write_drafts(
    backlog: Sequence[BacklogItem],
    profile: SiteProfile,
    *,
    llm: Any | None = None,
    trace: TraceWriter | None = None,
    run_id: str = "run",
    max_drafts: int = MAX_DRAFTS,
) -> tuple[dict[str, str], list[str]]:
    """Select, generate, gate and return drafts.

    Returns ``(drafts, rejected)`` where drafts maps ``slug.md`` to the
    gated copy and rejected lists the item ids that failed the compliance
    gate (never written to disk).
    """

    chosen = [item for item in backlog if item.kind in DRAFTABLE_KINDS][: max(0, max_drafts)]
    drafts: dict[str, str] = {}
    rejected: list[str] = []
    for item in chosen:
        if llm is not None:
            text, attempts = _llm_draft(item, profile, llm)
            if text is None:
                rejected.append(item.item_id)
                _emit(trace, item, "compliance_reject", run_id, attempts=attempts)
                continue
            _emit(trace, item, "compliance_pass", run_id, attempts=attempts)
        else:
            text = template_draft(item, profile)
            ok, violations = check_text(text, "draft", fca_firm_ref=profile.fca_firm_ref)
            if not ok:  # the template is supposed to pass; defence in depth
                rejected.append(item.item_id)
                _emit(trace, item, "compliance_reject", run_id,
                      attempts=1, rules=",".join(sorted({v.rule for v in violations})))
                continue
            _emit(trace, item, "compliance_pass", run_id, attempts=1)
        drafts[draft_slug(item.target)] = text
    return drafts, rejected


def _profile_entity(profile: SiteProfile) -> str:
    host = profile.domain.replace("https://", "").split("/", 1)[0]
    host = host.removeprefix("www.").removesuffix(".co.uk")
    return host.replace("-", " ").title()


def _head_keyword(item: BacklogItem) -> str:
    evidence = item.evidence or {}
    return str(evidence.get("service") or evidence.get("head_term") or item.gap_type or "this service")


def _emit(trace: TraceWriter | None, item: BacklogItem, kind: str, run_id: str, **extra: Any) -> None:
    if trace is None:
        return
    trace.emit(step="drafts", tool="draft", args={"item_id": item.item_id},
               source="code", status="ok" if kind.endswith("pass") else "rejected",
               kind=kind, **extra)


__all__ = [
    "DRAFTABLE_KINDS",
    "MAX_DRAFTS",
    "draft_slug",
    "llm_draft_messages",
    "template_draft",
    "write_drafts",
]
