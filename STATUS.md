# Status

Generated 2026-11-16 from the working tree at bd76f9e + uncommitted changes.
Every item carries file:line evidence. Nothing here is committed; see
"Cleanup" for the known defects and stale lines.

## Done (works, verified here)

- Deterministic pipeline (audit → gaps → backlog → report) — src/pipeline.py;
  fixture run green, `S12` byte-identical rerun passes (evals: frozen eight 8/8, --all 16/16).
- Test suite — 447 passed, 2 deselected on Python 3.14.8 (deselected =
  `tests/test_live.py::test_live_self_test_one_real_call` and
  `::test_live_client_budget_ledger_records_tokens`, both `@pytest.mark.live`,
  tests/test_live.py:1-21).
- Eval harness — frozen v1.2 eight in `evals/scenarios/` (`python -m src.cli evals` → 8/8 PASS); 8 extras in `evals/extra/` (`--extra` → 8/8, `--all` → 16/16 PASS).
- Compliance lint C1–C6 + C1b, negation-aware, per-rule pass/fail tests —
  src/compliance.py:71 (`_is_negated`), src/compliance.py:137 (C1b),
  tests/test_compliance.py (e.g. `test_C1b_permits_negated_no_fees` :99).
- Vendored seoextract pinned @ 6544a74e with capability probe tests —
  third_party/PROVENANCE.md, src/audit_adapter.py, tests/test_adapter.py:48,61,84,292.
- Placeholder-profile live-run refusal — src/cli.py:66-89 (requires
  `SEO_AGENT_ALLOW_DEMO_PROFILE=1` to crawl the demo site).
- Query→page GSC mapping (Option A, Pages export) — src/sources/gsc_pages.py:29,58;
  wired src/pipeline.py:173-189; consumed src/gap.py:118-133.
- CI config exists — .github/workflows/ci.yml (pytest + evals on 3.12/3.14).
- F-8 first-cycle baseline template — evals/first-cycle.md (untracked).
- Nearest-pages evidence (cap 5, stable) — src/gap.py:76; test
  tests/test_gap.py:293 `test_no_page_evidence_lists_nearest_pages_not_full_census`.
- Empty-source trace signal — src/sources/base.py:91-99 (`source_empty`).

## Partial

- GSC keyword demand is used, but clicks/impressions/CTR/position are
  discarded downstream — src/sources/gsc_csv.py:143-166 (`to_keywords`
  emits Keyword only); gap.py consumes no GSC scalars (src/gap.py:118-133).
- Report is silent when sources are absent — `grep -n -i "gsc"
  out/run-20261116T090000Z/report.md` → no match; sources appear only as
  `sources: keywords` per item (report.md:35-39) and `Fetches: 0 / 120`
  (report.md:86).
- SERP/Google Suggest: works but ToS-grey; undocumented endpoints, robots.txt
  never consulted, zero-block parse yields silent "no SERP" (only trace-visible
  via src/sources/base.py:91-99) — src/sources/serp.py:25, src/sources/suggest.py:21,
  src/sources/fetch.py:68.
- Money-keyword prioritization is honest but local pages outrank single-source
  NO_PAGE gaps via frozen dual-source confidence 0.65 vs 0.50 —
  src/backlog.py:59-77; S10 frozen weights.
- Drafts: written but manual adviser review not enforced by code (by design;
  banner says NOT REVIEWED — src/drafts.py:71-75).

## Not verified

- GitHub CI actually green (config exists; never run observed).
- Real live crawl against a real domain (profile still fictional —
  profiles/site.json = clearpath-mortgage.co.uk, FCA 123456).
- Real `--agent` run against NVIDIA NIM (agent tests are unit-level FakeLLM).
- Real GSC Queries.csv / Pages export anywhere (fixture only).
- SEO outcome metric (F-8): no baseline recorded; nothing measures rankings.
- AGENTS.md "on 3.12 and 3.14" claim — 3.12 not run on this machine.
- Placeholder guard refuses only the exact shipped pair, not other fictional values.

## Broken

- Nothing known-broken at runtime; suite green. Known doc defects:
- README.md literal `\n` — FIXED (uncommitted) at README.md:365-366.
- CODEBASE_REPORT.txt count self-contradiction — FIXED (uncommitted) at
  CODEBASE_REPORT.txt:28 ("441 passed, 2 deselected").

## Cleanup

- seo-agent-findings.txt — DONE: untracked via `git rm --cached` in 5abf778;
  `seo-agent-findings*` is gitignored.
- Stale lines: FIXED in 047cb33 (CI-absent claims in CODEBASE_REPORT.txt;
  CHANGELOG.md "429 passing" annotated). Dated 429 test-count snapshots
  remain intentionally (history).
- Leftover "gate" nouns: README.md:144, :178, :325, :338, :351;
  src/compliance.py:1; src/drafts.py:136,158,161-162; src/agent.py:237;
  src/cli.py:49; src/schema_gen.py:8; src/evals.py:164,180;
  CODEBASE_REPORT.txt:60,108,112,179,219; AGENTS.md:31 ("tests are the gate").
- 8 extra eval scenarios — DECIDED 2026-11-16: moved to `evals/extra/` via
  `git mv`; frozen v1.2 eight stay in `evals/scenarios/`; harness gains
  `--extra` / `--all`; README and this file updated.
- vulture (uvx, min-confidence 80): `src/store.py:230` — FIXED: param renamed
  to `_exc_info` (518e3d2).
- Working tree: clean at baseline-clean (5abf778), pushed; CI green.
- AGENTS.md / CODEBASE_REPORT.txt / CHANGELOG.md are hand-maintained snapshots
  that rot; regenerate or add a check.
