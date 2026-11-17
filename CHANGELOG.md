# Changelog

## 2026-11-17 — Phase 4 prep: N-17 disagreement taxonomy, N-18 fixture baseline

Two items settled before the Phase 4 live run and blind hand-rank:

- N-17 defines what counts as a pre-check disagreement (hand-rank excludes
  a reclassified item from the top 10 -> N-10 applies to the token rule)
  vs a scoring disagreement (included but ranked lower -> N-10 applies to
  the WEAK_PAGE impact/effort constants). Recorded before the hand-rank so
  the outcome is interpretable; one constant per commit.
- N-18 records the post-Phase-3 74kw fixture gap distribution as the
  Phase 4 comparison baseline: SCHEMA_MISSING 27, NO_PAGE 26, WEAK_PAGE 9,
  LOCAL_MISSING 6 (68 total, max 39.7%). Live run should be within ±5 per
  type and 5 ± 3 reclass count; compare against this, not the pre-Phase-3
  31/27/6/4.
- `BACKUP.md` added: bundle provenance and restore/copy-off instructions;
  the p3 bundle is on this disk only as of 2026-11-17.

## 2026-11-17 — Phase 3: NO_PAGE pre-check (N-5)

N-5's coverage check is implemented. Before any page-creation gap is
emitted, the engine looks for a crawled page with >=2 significant
head-term tokens across title + H1 + H2 combined (N-14) using the
pre-check stoplist (N-15: UK_MORTGAGE_STOPLIST minus `mortgage`). A match
produces WEAK_PAGE for that page with `matched_tokens` and per-field
`matched_fields` evidence, ahead of NO_PAGE.

- Gate result (N-16): 5 of 31 NO_PAGE reclassified on the 74-keyword
  landc fixture. All five enumerated and accepted. One borderline
  H2-only match recorded on the clearpath fixture; accepted as written,
  tighten only under N-10 with a hand-rank disagreement.
- Fixture `tests/fixtures/landc_audit_74kw.json` recorded from
  run-20261117T153658Z via the DB (50 pages, 146 issues). Ordering
  caveat in out/README.md reworded to the empirical claim (replayed:
  no items move in the three pinned runs).
- Consequences: golden eval S01 re-based (top item now meta_fix 2.0 on
  /first-time-buyer); S02/S2 widened to allow WEAK_PAGE; test_gsc_demand
  moved its query to 'bad credit mortgage' (the fees-explained cluster is
  now WEAK_PAGE). Intent of each test unchanged; the output change is the
  intended N-5 effect. New unit tests cover the N-14 field combination,
  the 2-token floor and the stoplist.
- Suite: 513 passed, 2 deselected. Evals green. Ruff clean.

## 2026-11-17 — Phase 2: backlog N-3 total order

No scoring change (N-4): tiebreaks reorder, priority values are untouched.

- The backlog sort key now matches N-3 exactly: (-priority, -is_money,
  -gsc_impressions, -money_kw_count, kind_rank, target, keyword, then a
  terminal discriminator). Two clarifications are recorded here because
  N-3 does not spell them out: (i) `kind_rank` orders kinds meta_fix 0 <
  schema 1 < create_local_page 2 < create_page 3 (mirrors the gap
  analysis severity order; quick, cheap items first); (ii) N-3's terminal
  `item_id` cannot be used literally because ids are positional
  (BL-0001.. assigned after the sort). The final key elements are
  `gap_type` ascending and then a stable content digest of the gap
  (normalised keyword, type, cluster, target, evidence, sources), which
  keeps the order total even between byte-different findings on the same
  keyword and target. Ids stay sequential by final position.
- `money_kw_count`: number of profile money keywords covered by the
  item's keyword set (`evidence["cluster_keywords"]` where present, else
  the item's own keyword). The sitewide SCHEMA_MISSING umbrella has no
  keyword set and counts 0 (it is an item, not a keyword), so the key
  never compares page counts against keyword counts; the umbrella orders
  by `kind_rank` among schema-kind items. This supersedes the earlier
  draft of this entry, which had the umbrella count its flagged money
  pages.
- The pre-Phase-2 secondary key (`effort`) is gone; the money flag is now
  the primary tiebreak after priority. Order changes where effort differs
  but money flag and GSC demand agree — that is the intended N-3
  behaviour (N-4: order only, priority unchanged).
- Dedupe of equal-priority identical (keyword, gap_type, target) gaps now
  keeps the smaller content digest instead of the first gap seen, making
  the output invariant under input permutation rather than merely stable.
- New tests: E5 shuffle gate — a representative gap list (money/non-money
  NO_PAGE with different cluster sizes, GSC-weighted pairs, audit-backed
  WEAK_PAGE/SCHEMA_MISSING, the schema umbrella, LOCAL_MISSING,
  COMP_COVERS, equal-priority duplicates with different evidence) shuffled
  across 20 fixed seeds yields byte-identical `model_dump_json` output.
  Tie tests: money (different `money_kw_count`, ordered by count before
  target); GSC (both money, equal `money_kw_count`, impressions 9 > 2 at
  equal 0.5 priority); terminal tie (COMP_COVERS before NO_PAGE on equal
  score/target/keyword; ids BL-0001/BL-0002 assigned by final position).
- Pinned reference runs (`out/run-20261117T143756Z/`, `T150656Z/`,
  `T153658Z/`) were produced with the pre-Phase-2 key and their ordering
  convention differs; N-6 forbids overwriting them, so this is recorded in
  `out/README.md` instead — do not diff ordering against them.
- Evals 16/16 (S12 byte-identical rerun green, S13 cap/order green).
  Suite: 510 passed, 2 deselected. Ruff clean.

Out-of-band DB cleanup (not part of the commit; `out/state/seo.db` is
gitignored): the synthetic `run-20261117T160000Z` row was deleted with its
child rows (audit_pages/issues, keywords, gaps, backlog). Its
`domain = landc.co.uk` label with clearpath-shaped pages would otherwise
have been picked as the landc baseline by `latest_run(completed_only=True)`;
baseline selection now resolves to `run-20261117T153658Z`. The tracked
evidence directory `out/run-20261117T160000Z/` remains, still labelled
evidence-not-baseline. This discharges the Phase 4 checklist item early.

## 2026-11-17 — Phase 0 reconciliation (numbers as measured)

- Evals: the "16/16 vs 8/8" discrepancy (C-1) is resolved. `evals` with no
  flag runs the frozen v1.2 eight (`evals/scenarios/`, 8/8); `--extra` runs
  `evals/extra/`; `--all` runs both (16/16). No scenarios were removed or
  renamed. Both numbers are correct for their flags.
- Suite re-run on this working tree: 494 passed, 2 deselected (`not slow
  and not live`).
- Ruff: one finding on the uncommitted week-plan code in `src/report.py`
  (B905, `zip()` without `strict=`). Fixed with `strict=True` (labels and
  buckets are the same length).
- Working tree at reconciliation: modified `profiles/landc.json` (widened
  to 74 keywords), `src/backlog.py`, `src/report.py`, `tests/test_backlog.py`,
  `tests/test_report_determinism.py` (tiebreaker + week plan, uncommitted);
  untracked `out/run-20261117T153658Z/`, `out/run-20261117T160000Z/`
  (post-tiebreak rerun), `out/backlog-handrank-20261117.md`,
  `seo-agent-backup-20261117.bundle`.
- `out/run-20261117T160000Z/report.md` reproduces the suspected cross-domain
  symptom ("Delta vs previous run: -1.6", clearpath-mortgage.co.uk URLs under
  "New issues since previous run", "Pages crawled: 6") on a landc run.
  Unverified until Phase 1 Step 1 reproduces it in a test.
- The backup bundle `seo-agent-backup-20261117.bundle` is complete only up
  to the last commit; it contains none of the uncommitted files above (C-6).
  Refresh it after the human commits.

## 2026-11-17 — schema umbrella money-page weighting, GSC pipeline test

- The SCHEMA_MISSING umbrella backlog item is now money-page-weighted: its
  evidence lists the flagged pages that are profile money pages
  (`money_urls`, passed by the pipeline and agent), `impact` is CRITICAL
  when at least one flagged page is a money page (WARNING otherwise), and
  the title reports the money-page count. On the landc profile the
  umbrella covers `/`, `/buy-to-let` and `/remortgage`, so it ranks first
  (0.375) instead of coasting at WARNING on all 17 pages. Conditions for
  that rank: the 10-keyword landc profile with no GSC data attached. On
  the 74-keyword profile (`out/run-20261117T153658Z/`, pre-tiebreak) it
  ranks #11 behind four WEAK_PAGE items at 2.0. The #1 rank is also
  conditional on the NO_PAGE items carrying no GSC demand: even
  modest GSC impressions (x1.1 at >=10) would put a coverage gap ahead of
  it. The rank holds for landc because there is no GSC data, and the
  umbrella is an impact-weighted grouping, not a confidence-weighted one
  (confidence stays CONFIDENCE_AUDIT = 1.0 either way; more pages do not
  raise audit confidence).
- Both `run_deterministic` and agent mode pass `gsc_demand=` into gap
  analysis; confirmed. New pipeline-level integration test drives
  `run_deterministic` with a fixture and `SEO_AGENT_GSC_CSV` set and
  asserts a GSC-backed NO_PAGE outranks an otherwise-identical GSC-less
  one end-to-end.
- Live re-run `run-20261117T150656Z` (no-llm): `Fetches: 52 / 120`,
  score 89.1 (B), 4 backlog items, evals 16/16.
- Fetch-budget refusal is now also tested at pipeline level, not just the
  adapter: a fake crawler spends the MAX_FETCHES budget mid-crawl and the
  run still yields a report, the trace carries the `budget` event
  (`reason=max_fetches`), and the audit snapshot keeps the synthetic-429
  page in a form gap analysis tolerates.
- Reference runs `out/run-20261117T143756Z/` and `out/run-20261117T150656Z/`
  (report.md + backlog.json only) are now pinned as frozen baselines for
  future comparison, with `out/README.md` explaining the convention; they
  are not regenerable from the current DB, which stays gitignored.
- Suite: 490 passed, 2 deselected (+2 umbrella money-weighting tests,
  +1 GSC pipeline integration test, +1 fetch-budget pipeline test).

## 2026-11-17 — real-site findings: diff scoping, fetch ledger, schema backlog

Addresses the four findings from the landc.co.uk live-run review
(`out/run-20261117T143756Z/`).

- Cross-site diff pollution fixed: `Store.latest_run` accepts a `domain`
  filter, the pipeline and agent now pick the previous run scoped to the
  same profile domain, and `Store.diff_runs` refuses a cross-domain
  baseline outright. When only other sites' runs exist, the report prints
  `Delta vs previous run: n/a (no comparable previous run for this
  domain)` instead of a fabricated cross-site delta and "issues closed".
- Fetch ledger covers the vendored crawler: the adapter's politeness
  wrapper now counts live-crawl GETs (pages + robots.txt) against
  `MAX_FETCHES` (120) and refuses further crawls with a synthetic
  429 page once the budget is spent; a `budget` trace event is emitted.
  `Fetches: n / 120` in reports now includes the audit crawl, not only
  source fetches. Fixture runs report 0.
- Schema degeneracy fixed in two steps: (1) SCHEMA_MISSING is now emitted
  only for keyword-cluster-relevant pages (slug or title/H1 overlap with a
  cluster head term), replacing "every 200 page lacking LocalBusiness/
  FinancialService/FAQPage"; (2) more than 3 such findings are grouped
  into a single umbrella backlog item whose evidence lists every flagged
  page. Schema knowledge remains in the report's gap list.
- GSC demand now weights backlog priority: a cluster with >=1000 / >=100 /
  >=10 impressions multiplies its gaps' priority by 1.5 / 1.25 / 1.1.
  Agent mode passes `gsc_demand` into gap analysis (it did not before).
- WEAK_PAGE requires >=2 shared significant slug tokens with the head term
  (capped by head-term size); the "remortgage calculator" ->
  loan-to-value-calculator single-token mapping is gone.
- Real-site regression baseline added: `tests/fixtures/landc_audit.json`
  (the recorded 2026-11-17 landc.co.uk crawl, public marketing copy, used
  for diff/gap regression only) + `tests/test_real_site.py` asserting a
  non-degenerate gap distribution, cluster-relevant schema flags and a
  non-schema-flooded backlog.
- New tests: cross-domain diff refusal, domain-scoped `latest_run`,
  fetch-ledger counting/refusal, schema umbrella grouping, GSC demand
  boost, landc regression (3).
- Suite: 486 passed, 2 deselected. Evals: frozen eight 8/8, --all 16/16.

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
## 2026-11-17 — Phase 10: hermetic seoextract pin

No spec revision. Closes the v1.2 review caveat that the pinned-commit guard
was not hermetic (it checked the config constant, `__version__` and the
capability probe, but not the vendored bytes).

- New `third_party/seoextract/VERSION` (and the identical bundled copy under
  `src/resources/third_party/seoextract/VERSION`): contains the upstream
  commit hash `6544a74e340e6ac8b147b7f4ab0f09d55d142dd3`, written at
  vendoring-fix time. Not imported by seoextract at runtime.
- `tests/test_packaging.py` gains `test_vendored_version_files_match_pin`,
  asserting both copies byte-match `config.SEOEXTRACT_COMMIT`. The guard is
  now self-consistent against the actual vendored bytes without needing git
  in CI.
- `third_party/PROVENANCE.md` records the addition under "Local additions"
  per the edit policy; upstream files remain verbatim.

## 2026-11-17 — orchestration de-dup (Fix 5)

- The deterministic pipeline and the agent loop persisted the six run stages
  and rendered/wrote the report through duplicated blocks. Both now call the
  shared `save_run_stages`, `previous_baseline` and `render_and_write_run`
  in `src/pipeline.py`; behaviour and byte-identical fixture reruns are
  unchanged (Suite: 490 passed, 2 deselected; evals 16/16).
- `vulture --min-confidence 80` on `src/` is clean; no dead code to remove
  (Fix 3). Fix 7 (trim periphery) remains deferred: agent mode, drafts and
  the scraping modules stay experimental and are documented as unproven,
  not deleted.
- profiles/landc.json `fca_firm_ref` is still the placeholder `000000`; the
  FCA register blocks automated lookup, so the real FRN needs a manual
  check on register.fca.org.uk before any compliance lint on drafted copy
  is trusted.

## 2026-11-17 — Phase 1: baseline trust (domain-scoped, total normalisation)

- Root cause of the suspected cross-domain delta (run-20261117T160000Z):
  that run row was written with url=landc.co.uk but clearpath-shaped audit
  pages (all fetches latency 0, audit source cache) — a fixture payload
  written through the live DB path. Baseline *selection* in
  `previous_baseline` was not the culprit; it already filtered by stored
  url, but did so with exact string match and no domain column, so any
  www/port/case/scheme difference silently produced "no baseline", and
  cross-domain diffs still produced a fabricated score delta
  (`current - 0.0`).
- Fixes (N-1, N-2): `config.normalize_domain` (lowercase host, leading
  www. stripped, port stripped); `runs` gained a `domain` column populated
  at write time with an idempotent migration that backfills existing rows
  in one transaction; `latest_run` matches on the normalised domain and can
  require completed (`status='ok'`) runs; `_same_domain` compares
  normalised keys; `diff_runs` cross-domain guard stays and
  `AuditDiff.score_delta` is now `None` without a same-domain baseline (a
  number never appears without one); the missing-baseline note renders the
  literal N-2 sentence "No comparable previous run for <host>.".
- Tests: `tests/test_baseline_scoping.py` — mixed-DB pipeline repro,
  only-other-domain case, P1-R1..R6 table rows (R4: www/bare/port/case/
  scheme all one domain, R5: incomplete runs never a baseline, R6:
  cross-domain diff_runs yields no closed items and `score_delta=None`).
  Suite: 506 passed, 2 deselected. Evals 16/16. Ruff clean.
- `out/state/seo.db` (gitignored) backfilled: all landc runs keyed
  `landc.co.uk`, clearpath runs `clearpath-mortgage.co.uk`.
- `out/run-20261117T160000Z/` stays tracked but is now labelled in
  `out/README.md` as evidence, not a baseline: it is the synthetic fixture
  row that produced the suspected symptom, not a valid landc reference.
