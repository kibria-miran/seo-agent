# Changelog

## 2026-11-16 — report sources, GSC demand and scraping policy

Owner answers Q5 recorded 2026-11-16 (DECISIONS.md): scraping off by default.

- GSC metrics (clicks/impressions/CTR/position) now flow from the Queries.csv
  parse through keywords into gap evidence (`evidence["gsc"]`, aggregated per
  cluster) and into the backlog items derived from those gaps. New
  `gsc_demand_for` in the pipeline; new report section "GSC demand (from your
  export)" (absent when no GSC data). Keywords table gained nullable
  `gsc_*` columns with an idempotent ALTER TABLE migration.
- Report: explicit `## Source data` section when sources ran — each source
  lists its item count, or "no data from <source>" (with attempt count and a
  possible-block note when every attempt returned zero rows). Absent on the
  default fixture path.
- Scraping policy: `--with-sources` now enables only the file-based GSC
  ingest (never touches the network); new `--with-scraping` flag enables the
  ToS-grey Suggest/SERP scraping and competitor discovery. Off by default.
  Agent mode honours both flags.
- Suite: 464 passed, 2 deselected. Evals: frozen eight 8/8, `--all` 16/16.

## 2026-11-16 — v1.2 remaining fixes

No spec revision; continues the 2026-11-16 v1.2 review.

- Success metric (F-8): first-cycle baseline template added at
  `evals/first-cycle.md` (pre-change GSC impressions/clicks/CTR/position per
  target and money keyword, dated change log per applied backlog item with
  reviewer, 4–6 week re-check). Linked from README Documentation and the
  DECISIONS F-8 note. Operational, not code; not run in CI.
- C11: evidence blobs for NO_PAGE / LOCAL_MISSING / WEAK_PAGE gaps now list
  the nearest pages by slug-term overlap (cap 5, alphabetical fill, byte-
  stable) instead of the full crawled page census. Determinism preserved;
  one new test pins the cap.
- C3: sources that collect zero items now log a `source_empty` trace event
  (cached/HTTP rows/dropped items distinguishable), so a site-redesign that
  silently empties SERP results is visible in the trace instead of looking
  like "no SERP".
- Suite: 441 passed, 2 deselected. Default path byte-identical (S12
  PASS), evals 16/16.

## 2026-11-16 — v1.2 review fixes

No spec revision. Recorded from the v1.2 review (seo-agent-findings.txt,
local). The v1.2 spec document is still not in the repo; DECISIONS.md gained a
"v1.2 review supersessions" section instead.

- Compliance is now labelled everywhere as a lint, not a gate: README first
  paragraph + Safety model + Phase 7 + sample sections, `report.md` header
  (compliance disclaimer on every generated report), draft banner ("THIS
  DRAFT HAS NOT BEEN REVIEWED"), DECISIONS (D-6 row amended, F-4 note, lint
  wording in implementation notes), AGENTS.md. C1b is now negation-aware in
  line with C1/C6 (one new test).
- `render_report` adds the compliance disclaimer block (F-4). Report is not
  bare of disclaimers anymore; `out/run-20261116T090000Z/report.md` is
  regenerated with the new template (score unchanged: 87.5 B).
- Live runs against the placeholder demo profile
  (`clearpath-mortgage.co.uk` + FCA `123456`) are now refused by the CLI
  unless `SEO_AGENT_ALLOW_DEMO_PROFILE=1`; `doctor` PASSes the profile but
  WARNs on the placeholder. New tests/test_placeholder_profile.py.
- New `GscPagesSource` (env `SEO_AGENT_GSC_PAGES_CSV`): query→page mapping
  from a two-column CSV (prepared by the operator, e.g. from the free
  Search Console API dimensions=query,page). Wired into the pipeline when
  `--with-sources`; surfaces as `gsc_pages` evidence keys in NO_PAGE /
  WEAK_PAGE / LOCAL_MISSING / COMP_COVERS gaps and as a `gsc_pages` entry in
  the report's Run budgets block when sources ran. New tests/test_gsc_pages.py.
- Deterministic default path unchanged: report and backlog byte-identical
  for same run-id+fixture+clock, and evals still 16/16.
- `ddgs` was declared but never imported or wired; removed from pyproject
  and recompiled hashed requirements (uv). SERP/Suggest keep the undocumented
  HTML endpoints, now documented with their ToS caveat in README.
- CI added: .github/workflows/ci.yml runs pytest + evals on Python 3.12 and
  3.14. pyproject declares classifiers 3.10–3.14.
- README rewritten to match code/artefacts: phases 0–9 all complete;
  stale CLI paragraph and sample backlog excerpt corrected; doctor and
  scripts/weekly.sh documented in-body; Python CI claim corrected;
  compliance first-paragraph lint disclaimer.
- AGENTS.md corrected; CODEBASE_REPORT.txt amended (phase-8/git/CI claims
  were wrong).
- Suite: 440 passed, 2 deselected (both `live`-marked, tests/test_live.py;
  no `slow`-marked tests exist).

## 2026-11-16 — implementation start (spec v1.1)

No spec revision was made. Three implementation clarifications were forced by
the real vendored source and by D-15; they are recorded as R-1..R-3 in
`DECISIONS.md`.

- Vendored `seoextract` at `6544a74e340e6ac8b147b7f4ab0f09d55d142dd3` (v0.3.0).
- Confirmed API: `SEOExtract` at package root; `AuditResult`, `PageData`,
  `SEOIssue`, `Severity` in `seoextract.models`; `meta_description`,
  `h1_tags`, `audit_date` are the real field names. `audit_adapter.py` owns the
  translation.
- `probe_capabilities()` raises `ImportError` naming every missing symbol.
  Because `-m fast` must run from fixtures even without a network audit, a
  missing vendored checkout defers the error until `run_audit` is called
  without a fixture (R-2).
- Broken-link checks will use GET, not HEAD, to keep D-15's GET-only invariant
  enforceable (R-3).
- Created the deterministic Phase 0/1 skeleton: `config.py`, `clock.py`,
  `models.py`, `compliance.py`, `backlog.py`, `audit_adapter.py`,
  `conftest.py` and the first five test modules. No `agent.py` exists yet
  (D-11).

## 2026-11-16 — Phase 1 hardening

No spec revision. All changes enforce existing decisions.

- Added `src/security.py`: HTML-comment and `data-*` stripping, NFKC,
  Cyrillic/Greek homoglyph folding, combining-mark removal, zero-width
  stripping and case folding. A marker hit drops the whole fetched text; the
  caller logs `injection_attempt` and continues (D-4).
- Fixed homoglyph folding for uppercase Cyrillic/Greek forms by case-folding
  before translation, and neutralised entity-decoded
  `<untrusted_web_content>` delimiters so page text cannot break out of the
  labelled data block.
- Derived money keywords from `money_pages` slugs instead of treating every
  target keyword as money, so the CRITICAL impact rule stays meaningful.
- Moved the SQLite snapshot and future source cache to `out/state/` and
  `out/cache/`. D-15 permits writes only under `out/` and `logs/`; the previous
  `data/` and `cache/` roots did not satisfy that. Default DB is now
  `out/state/seo.db`; `--db` still overrides it.
- Added `README.md` with quickstart, sample report, safety model, weekly cron /
  systemd setup and an honest implemented-vs-remaining table.
- Added `requirements.txt` and `requirements-dev.txt` (uv-compiled, sha256
  hashes) and `requirements-seoextract.txt` (local path, never PyPI). The
  vendored fork is still imported from `third_party/` via `sys.path`.
- Added `tests/test_security.py` over `evals/injection_payloads.json` plus
  ordinary-copy false-positive checks and delimiter-breakout tests. Full suite:
  326 passing.

## 2026-11-16 — Phase 2: keyless live sources

No spec revision. D-3 (one Source interface, cache + throttle), D-4
(untrusted text), D-5 (robots, 2 s, honest UA), D-9 (TTL cache), D-14
(dep_unmet skip) and D-15 (GET only) all hold.

- New `src/sources/base.py`: `Source` ABC — requirements check (`dep_unmet`
  skip, never an exception), TTL cache via the Store (`source|query` key),
  per-host 2 s throttle shared by every source, injection scrubbing of
  untrusted `keyword`/`title`/`snippet`/`text` fields before caching, and
  trace events (`injection_attempt`, `dep_unmet`, `mine_sources`).
- `src/sources/competitor.py` — competitor discovery via keyless DuckDuckGo
  `site:` queries (money + target seeds, rounded out to `MAX_SERP_QUERIES`),
  hard-stopped at `MAX_FETCHES`. Each domain keeps at most `MAX_COMP_PAGES`
  page(s). Parsed pages carry title, meta description, H1–H6 buckets,
  word count and JSON-LD schema types. Injection-bearing pages are dropped
  whole and logged; robots-blocked and failing pages degrade gracefully.
  Parsed pages are TTL-cached per URL so reruns are cheap. Two competitor
  domains covering one head term now produce `COMP_COVERS` gaps end-to-end
  (keywords + two domains = multi-source confidence, 0.8).
- `src/sources/fetch.py` rewritten: shared `http_get` (GET-only, honest UA,
  1 MB cap, per-host throttle, counts fetches toward the D-13 budget),
  `robots.txt` memoisation (unreachable robots = allow, RFC 9309), `fetch_page`
  returns cleaned text only.
- `src/sources/suggest.py` — Google Suggest (`client=firefox`), normalised,
  de-duplicated, capped at 10 candidates per seed; seeds = money-page keywords
  + target keywords.
- `src/sources/serp.py` — DuckDuckGo HTML parser, top 10 organic results,
  `utm`-style redirect unwrapping, ads skipped; titles/snippets are scrubbed.
- `src/sources/gsc_csv.py` — Search Console Queries.csv (local file or
  `SEO_AGENT_GSC_CSV`); defensive header matching, thousands separators and
  percent signs tolerated; cache key fingerprinted on file size+mtime so a
  fresh export never serves stale rows. Unconfigured = `dep_unmet` skip;
  configured-but-missing = explicit error.
- Pipeline: opt-in `with_sources=True` / `--with-sources` merges mined
  keywords and persists SERP results before gap analysis; a single SERP
  match lifts a keyword-only gap from single- to dual-source confidence.
  Default runs are unchanged and byte-identical for the same run-id/fixture/
  clock; `save_serp` is populated (empty list when sources are off).
- 25 new tests (`tests/test_sources.py`): parsing, cache hit/miss, GSC
  fingerprint, `dep_unmet` vs configuration error, robots disallow/allow,
  throttle remainders, injection drops, pipeline merge and budget accounting.
  Full suite: 351 passing.

## 2026-11-16 — Phase 3: competitor coverage evidence

No spec revision. D-3, D-4, D-5 (max 5 pages per domain, robots, 2 s, honest
UA), D-9 (per-URL page cache), D-13 (fetch budget) and D-15 all hold.

- Opt-in `--with-sources` now also mines competitors: keyless DDG `site:`
  queries for each (money/target seed, competitor) pair (capped at
  `MAX_SERP_QUERIES`), then fetches up to 5 pages per domain (JSON-LD schema
  types extracted before any stripping). Non-2xx, robots-blocked and
  injection-bearing pages are skipped/dropped, never fatal.
- Competitor pages flow into gap analysis, the report ("Competitor coverage")
  and the SQLite snapshot (`run_id` cascade). Two domains covering a head term
  yield a `COMP_COVERS` gap with multi-source (0.8) confidence.
- `_strip_fragment` no longer rstrips `/` (it changed the canonical URL and
  broke staged-fixture fetches); fragments are still removed.
- New tests in `tests/test_competitor.py` cover parsing (schema, headings,
  word count), injection drops, per-domain cap, fetch-budget stop, page-level
  cache reuse, robots handling and the end-to-end `COMP_COVERS` path.
  Full suite: 361 passing.

## 2026-11-16 — Phase 4: eval harness (S01–S16)

No spec revision.

- New `src/evals.py`: scenario loader + checker vocabulary; every checker is
  in-process and pins an injected clock, so the deterministic scenarios stay
  byte-stable. A broken checker is reported as a failed scenario, never raised
  through the harness.
- 16 scenarios in `evals/scenarios/*.json`: golden baseline, clean-site gaps,
  compliance C1/C2/C5 + negation, injection corpus, frozen budgets,
  money-keyword impact, confidence weights, stale-run abort, byte-identical
  rerun, backlog cap/order, FCA validation, two-run diff, `COMP_COVERS`.
- `evals/baselines.json` committed as the regression anchor for the fixture
  run (score 87.5, grade B, 5 backlog items, BL-0001). Results land in
  `evals/results/` which is gitignored.
- CLI: `seo-agent evals` (exit 1 on failure) and `seo-agent evals --list`.
- New `tests/test_evals.py`: full-suite pass, unknown-kind/failing-checker/
  exception-isolation checks, CLI exit codes. Suite: 369 passing.

## 2026-11-16 — Phase 5: LLM client

No spec revision. D-2, D-13, D-15 all enforced in code; nothing here is
prompt-based.

- New `src/llm.py`: minimal NIM (OpenAI-compatible) chat client with an
  injectable transport (no hard dependency on the network for tests; the
  default transport lazy-imports the `openai` SDK with `max_retries=0`).
- Budget ledger (`LLMBudget`): every API attempt — including retries —
  decrements `MAX_LLM_CALLS`; an estimate (chars/4) rejects over-budget
  prompts before spending a single token; cumulative tokens and wall-clock
  seconds are capped by `MAX_TOKENS_IN` / `MAX_TOKENS_OUT` /
  `MAX_LLM_SECONDS`. CLI fixture path records the ledger into `store`
  (llm_calls/tokens) as today (0/0 for --no-llm).
- Retry with exponential backoff (1 s, 2 s) on 429/5xx/timeouts/connection
  errors; other failures are permanent. `_safe_detail` redacts key-shaped
  strings from any error text.
- Token usage falls back to the chars/4 estimate when the server omits
  `usage` (some NIM snapshots do).
- The API key never reaches the trace (`tool=llm_chat`, hashed args, token
  counts and latency only) and never reaches an exception message.
- `tests/test_live.py` holds the two opt-in `-m live` smoke tests (one real
  call + ledger check); they require `NVIDIA_API_KEY` and never run in the
  default suite. Full suite: 390 passing (live tests skipped).

## 2026-11-16 — Phase 6: agent tool loop

No spec revision. D-2, D-4, D-11, D-12, D-13, D-14 all enforced in code.

- New `src/agent.py`: `AgentRunner` + `Tool` registry. The LLM proposes one
  JSON tool call per turn; code parses, validates args against a per-tool
  schema, checks declared requirements (`dep_unmet` skip, D-14) and executes
  a thin deterministic wrapper around existing pipeline code. The agent adds
  ordering and annotation — no new business logic.
- Fallback contract (conftest): two consecutive failing proposals fall back
  to the deterministic template; the same `(tool, args)` twice consecutively
  trips the loop guard (repeats with new args are permitted). LLM budget
  exhaustion (`BudgetExceeded`) falls back immediately instead of burning
  steps against an empty ledger.
- Observations are structural summaries (counts, types, top targets) and any
  free text passes the injection scrub; raw HTML never reaches the LLM.
- `--agent` CLI flag; mutually exclusive with `--no-llm` (exit 2). Without
  `NVIDIA_API_KEY`, agent mode exits 2 naming the variable. Default remains
  the deterministic `--no-llm` path.
- Tool calls and LLM ledger are persisted: `finish_run` records real
  `llm_calls`/tokens, trace events carry hashed args.
- 18 new tests (`tests/test_agent.py`) including the two contract tests
  (two-bad-proposals fallback, loop guard), dep_unmet skip, budget guards,
  injected-title opacity and zero-network fixture agent runs.
  Suite: 408 passing.

## 2026-11-16 — Phase 7: compliance-gated drafts

No spec revision. D-2, D-6, D-7, D-12 enforced in code.

- New `src/drafts.py`: `template_draft` (deterministic, disclosure-complete,
  byte-stable) and the LLM path. One retry with the violations fed back;
  still failing → the item is rejected and `compliance_reject` is traced.
  Nothing is written before the gate clears it, in either mode.
- Draftable kinds: `create_page`, `create_local_page` (top three). Template
  includes the verbatim repossession risk warning, the FCA firm reference
  sentence and the fee disclosure sentence from config.
- `--with-drafts` flag on `run`; honoured by both the deterministic path
  (template drafts) and agent mode (LLM drafts; template in fallback, never
  re-spending budget on already-written drafts). Default runs unchanged and
  byte-identical.
- Fixed a subtle agent double-spend: drafts are generated once per run; the
  idempotent completion path no longer re-calls the LLM for copy that
  already exists.
- 14 new tests (`tests/test_drafts.py`): gate-before-write on both paths,
  gate regression protection, retry-with-feedback, byte-identical template
  reruns, agent LLM draft flow, CLI end-to-end. Suite: 422 passing.

## 2026-11-16 — Phase 8/9: scheduler, doctor, repository hygiene

No spec revision.

- `seo-agent doctor`: local-only self-check (profile validity + FCA ref,
  money-keyword derivation, writable `out/`+`logs/`, vendored seoextract
  import + capability probe, optional `NVIDIA_API_KEY`/`SEO_AGENT_GSC_CSV`
  reported as INFO, never FAIL). Exits 2 on any problem; the weekly script
  runs it first. 6 new tests.
- `scripts/weekly.sh`: POSIX sh, `set -eu`, doctor then the polite live
  deterministic run, appends to `logs/weekly.log`; honours
  `SEO_AGENT_SITE`. Tested by `sh -n` parse and content assertions.
  Cron/systemd docs in README now reference the script.
- Initialised a scoped git repository **inside** `seo-agent/` so the required
  files (`DECISIONS.md`, `CHANGELOG.md`, `third_party/PROVENANCE.md`,
  `README.md`, requirements with hashes) are tracked. The parent
  `/home/kibria` root repo was deliberately left untouched.
- Suite: 429 passing at the time (441 after the v1.2 review fixes).
