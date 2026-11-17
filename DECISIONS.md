# Decisions index

Spec version: **v1.1** (frozen). Status is `frozen` unless a test forces a
revision, in which case the revision is recorded in `CHANGELOG.md` and the row
is marked `amended`.

| ID | Decision | Status |
|---|---|---|
| D-1 | seoextract is the audited layer, vendored at a pinned commit and wrapped by `audit_adapter.py`. Gaps are built in our code. | frozen |
| D-2 | LLM proposes, code decides. | frozen |
| D-3 | No paid APIs; every source sits behind one `Source` interface with cache + throttle. | frozen |
| D-4 | Fetched web text is untrusted data; raw HTML never reaches the LLM. | frozen |
| D-5 | Own site max 50 pages; competitors max 5 each; robots respected; 2 s/host; honest UA. | frozen |
| D-6 | Compliance gate (`compliance.py`) runs before any public-facing draft is written. | frozen (amended: see v1.2 review — wording now "lint", invariant unchanged) |
| D-7 | Human in the loop; the agent never edits or publishes the site. Output is files. | frozen |
| D-8 | SQLite snapshot per run; diffs computed by code. | frozen |
| D-9 | Idempotent runs; cache key `source\|query` + `ttl_seconds` (not calendar date). | frozen |
| D-10 | All timestamps go through `src.clock.now()` (UTC). Report body is timestamp-free. | frozen |
| D-11 | `tests/conftest.py` + `tests/test_smoke.py` pass before any `agent.py` line exists. | frozen |
| D-12 | `--no-llm` path is fully deterministic with zero LLM calls. | frozen |
| D-13 | Budgets enforced by code (steps, calls, tokens, LLM seconds, fetches, run seconds). | frozen |
| D-14 | Tool registry declares `requires=[]`; unmet dependencies are skipped and logged as `dep_unmet`. | frozen |
| D-15 | Writes only under `out/` and `logs/`; HTTP GET only (except the LLM POST); no secrets in trace. | frozen |

## Forced revisions

- **R-1 (audit adapter API):** the real 0.3.0 names are in
  `seoextract.models`, and `PageData.meta_description` is not `meta_desc`.
  Only `audit_adapter.py` and `third_party/PROVENANCE.md` differ from section
  8.1. A capability probe test enforces this.
- **R-2 (import-time probe):** the probe runs when the vendored package is
  importable. A missing vendored checkout does not break `-m fast`; it raises
  a clear `ImportError` only when a network audit is requested, so
  fixture-injected tests remain runnable (I-15).
- **R-3 (HEAD requests):** D-15 says GET only, so our broken-link checker uses
  GET rather than HEAD. This supersedes the HEAD wording in 8.1 and keeps the
  HTTP-method safety invariant test strict.

- **R-4 (fetch ledger covers the audit crawl):** the adapter's politeness
  wrapper counts live-crawl GETs (pages + robots.txt, 2 per crawl) against
  `MAX_FETCHES` and returns a synthetic 429 page once the cap is reached.
  `Fetches: n / 120` in reports now includes the crawl, satisfying D-13 as
  written rather than as previously implemented. Fixture runs report 0.

## Implementation notes (not revisions)
- 2026-11-17 umbrella weighting: the SCHEMA_MISSING umbrella item takes the
  impact of its money pages, not all flagged pages — `impact` is CRITICAL
  when any flagged page is a profile money page, else WARNING, and the
  evidence lists `money_pages` / `money_page_count`. The item is an
  impact-weighted grouping, not a confidence-weighted one: confidence
  stays CONFIDENCE_AUDIT = 1.0 regardless of how many pages it covers.
  Its "ranks first" outcome on landc is conditional on the NO_PAGE items
  carrying no GSC demand; modest GSC impressions (x1.1 at >=10, x1.25 at
  >=100, x1.5 at >=1000) would reorder it behind a coverage gap.

- 2026-11-17 scoring behaviour: gaps tied to a cluster with GSC impressions
  are priority-weighted x1.5 / x1.25 / x1.1 (>=1000 / >=100 / >=10
  impressions). More than 3 SCHEMA_MISSING findings for keyword-relevant
  pages are grouped into one umbrella backlog item (evidence lists every
  page); the gap list keeps the per-page entries for the report.
- 2026-11-17 schema policy: SCHEMA_MISSING fires only on pages that are
  keyword-cluster-relevant (slug or title/H1 overlap with a cluster head
  term), not on every crawled 200 page. WEAK_PAGE requires >=2 shared
  significant slug tokens (capped by head-term size).
- 2026-11-17 diff policy: run-vs-run diffs are computed only against a
  previous run for the same profile domain; cross-domain baselines are
  refused and the report prints "n/a (no comparable previous run for this
  domain)".


- The SQLite snapshot defaults to `out/state/seo.db` and the source cache to
  `out/cache/`, so D-15's write allowlist (`out/`, `logs/`) holds for every
  default path. `--db` remains an explicit override.
- Money keywords are derived from `money_pages` slugs. Treating the whole
  target list as money would make the CRITICAL impact rule apply to everything.
- Live sources declare `requires` as environment variable names and are skipped
  with a `dep_unmet` trace event when unset (D-14). Only the GSC CSV source
  uses this today (`SEO_AGENT_GSC_CSV`); a configured-but-missing file is an
  explicit error, not a skip.
- The GSC source's cache key fingerprints the export (name/size/mtime) rather
  than using a fixed query string, so a refreshed export is never served stale
  rows within the 24 h TTL.
- Sources are strictly opt-in (`--with-sources`); the default deterministic
  path never touches the network and remains byte-identical for the same
  run-id, fixture and clock.
- Competitor discovery uses DuckDuckGo `site:` queries (no key, no account).
  At most `MAX_SERP_QUERIES` discovery queries per run and `MAX_COMP_PAGES`
  pages per domain; discovery and page fetches both count toward the
  `MAX_FETCHES` budget and the loop hard-stops at the cap.
- Parsed competitor pages are cached per URL (`competitor_page|<url>`) inside
  the TTL cache so a repeated run does not re-fetch or re-parse.
- Eval scenarios live in `evals/scenarios/*.json` with a deliberately small
  checker vocabulary in `src/evals.py`. The committed regression anchor is
  `evals/baselines.json`; eval results are runtime artifacts and gitignored.
- LLM budgets are enforced per *attempt*, not per completed call: a retry is
  still an API call and still counts against `MAX_LLM_CALLS`. Over-budget
  prompts are rejected before any tokens are spent, using a chars/4 estimate;
  the server-reported usage reconciles the ledger after the call. If the
  server omits `usage`, the estimate is used for the ledger too.
- `LLMClient`'s default transport passes `max_retries=0` to the OpenAI SDK so
  all retries flow through our ledger, not the SDK's invisible retry layer.
- The agent retries a bad proposal exactly once before the deterministic
  template fallback: two consecutive failures fall back, and hitting any
  LLM budget falls back immediately. The loop guard trips only on the SAME
  (tool, args) pair twice consecutively; repeats with new args are allowed.
- Tools declare `requires` as environment variable names; an unmet
  requirement is logged as `dep_unmet` and the tool is skipped, never run.
  `check_compliance` demonstrates the pattern; no current tool requires
  anything (kept empty by design, D-14).
- Draft generation is linted before the write, never after: the deterministic
  path uses a disclosure-complete template (byte-stable); the agent path lets
  the LLM propose and the lint decide, with exactly one feedback retry. A
  template that fails the lint is dropped, not shipped — the lint is the
  authority in both modes, but it is a lint, not a compliance review. Drafts
  are written once per run; the idempotent
  completion path never re-spends LLM budget on copy that already exists.

## v1.2 review supersessions (recorded 2026-11-16)

The v1.2 spec document is not in this repo; this section records what the
v1.2 review (see `seo-agent-findings.txt`, local only) found and how the
tree stands now. Where these items conflict with the frozen v1.1 rows, the
review brief takes precedence.

- **F-1 (LLM scoped to cluster labelling and brief drafting; planner
  dropped; fixed pipeline).** The LLM never appears on the default path
  (zero calls); agent mode remains opt-in only. A "planner" never existed
  here. D-2 is reinterpreted as scoped to `--agent`.
- **MAX_STEPS / loop guard / invalid-action handling** apply only inside the
  opt-in agent loop. They are not part of the default pipeline and carry no
  spec weight for it.
- **F-2 (GSC is core).** The tree keeps GSC opt-in with `dep_unmet` skip
  when unconfigured, which is honest for a profile that ships no real
  Queries.csv. Query→page attribution is now supported through a new
  `GscPagesSource` (env `SEO_AGENT_GSC_PAGES_CSV`), carrying query→page
  pairs from a two-column CSV (prepared from the free Search Console API or
  per-page Queries exports). Zero paid APIs; the Source interface and cache
  discipline are unchanged.
- **F-4 (compliance is a lint, not a gate).** README, `report.md`, drafts,
  DECISIONS and the code all state explicitly that: the C1–C6 checks are
  pattern matching; passing them does not make output compliant; a
  qualified adviser must review every draft before publication. D-6's
  invariant (checks run before any write, in both modes) is unchanged; the
  wording everywhere is now "lint", never "authority". C1b is now
  negation-aware in line with C1/C6, and a negated "no fees" test pins
  this.
- **F-3 (seoextract Plan B).** No change required: provenance is complete,
  probe tests pass, a requests+bs4 replacement is small if ever needed
  (~200–450 LOC).
- **F-8 (success metric).** The first-cycle baseline template now lives at
  `evals/first-cycle.md`: record GSC impressions/clicks/CTR/position for
  target and money keywords before any site change, log each applied
  backlog item with its reviewer, and re-check after 4–6 weeks. Using it is
  operational, not code; it does not run in CI.

See `CHANGELOG.md` for dates and context.

## Owner answers (2026-11-16)

Recorded verbatim from the owner via question tabs. bd76f9e is NOT ratified
by this section; no sign-off is implied.

- Q1 (use case): a real client/business.
- Q2 (audit target): https://commercialmortgageadvisorsnearme.co.uk/
- Q3 (GSC): yes, Search Console access exists. Export method and file
  location not yet specified (follow-up needed before D2).
- Q4 (LLM provider): OpenRouter. Whether the API key is set in env:
  not yet confirmed (follow-up needed before D3). Key must not be printed.
- Q5 (Suggest/SERP scraping ToS risk): off by default.
- Q6 (scheduling): manual runs only; no cron/systemd timer for now.
- Q7 (report audience/format): owner only; markdown is sufficient.
- Q8 (out/ tracked): yes, keep out/ report.md and backlog.json tracked as
  definition-of-done samples.
- Q9 (repo visibility): keep public. History scan found only test-fixture
  keys (nvapi-testkey..., nvapi-abcdefghijklmnop used in redaction tests),
  no real secrets.
- Q10 (definition of "productive"): accepted the proposed sentence:
  "one command produces a correct report for a real site, with tests, CI
  green, README, and a documented setup."
- Q11 (deadline): none.
- Q12 (cut scope): nothing cut.

Follow-ups recorded 2026-11-16:

- GSC export method: UI CSV export; file to live at secrets/gsc-queries.csv
  (gitignored; never committed).
- OpenRouter API key: NOT set in env as of 2026-11-16. Needed before D3.
- SEO_AGENT_CONTACT: "kibria".
- Real profile values for commercialmortgageadvisorsnearme.co.uk: owner will
  provide later (money_pages, target_keywords, competitors, cities, FCA firm
  reference or instruction to make the FCA ref optional for non-UK finance).
  Phase B is blocked until then.
- 2026-11-17 orchestration: run-stage persistence, previous-baseline
  selection and report render/write are shared between the deterministic
  pipeline and agent mode via `save_run_stages` / `previous_baseline` /
  `render_and_write_run` in `src/pipeline.py`. The agent keeps its own
  budget shape and idempotent mid-loop persist; only the mechanics moved.

## Product-chapter decisions (2026-11-17, N-1..N-13, frozen)

- **N-1.** Baselines are domain-scoped with NO unscoped fallback anywhere:
  latest_run, previous_baseline, diff_runs, report rendering. Domain key =
  lowercase host, leading "www." stripped, port stripped.
- **N-2.** A missing or cross-domain baseline renders the literal sentence
  "No comparable previous run for <host>." Delta fields are None. A number
  must never appear without a same-domain baseline.
- **N-3 (amended 2026-11-17).** Backlog order is a TOTAL order,
  deterministic under input shuffling: (-priority, -is_money,
  -gsc_impressions, -money_kw_count, kind_rank, target, keyword,
  gap_type, content_digest). The terminal `item_id` from the original
  wording is removed: ids are positional (BL-0001.. assigned after the
  sort), so they cannot discriminate the items that produce them — they
  are an output of the sort, not an input. `gap_type` ascending and then
  a stable digest of the gap's content (normalised keyword, type,
  cluster, target, evidence, sources) stand in for it and keep the order
  total even between byte-different findings on the same keyword and
  target. `kind_rank` orders kinds meta_fix 0 < schema 1 <
  create_local_page 2 < create_page 3 (cheapest, quickest first); N-3
  did not define it. Byte-identical rerun (S12) stays green.
- **N-4.** Tiebreakers change ORDER only, never the priority value.
  Priority = impact x confidence / effort x gsc_multiplier, as today.
- **N-5.** NO_PAGE is emitted only after a coverage check. If any crawled
  page has >= 2 significant keyword tokens in title, H1 or H2 (stopwords
  pinned in config.py), the gap becomes WEAK_PAGE for that page, not
  NO_PAGE.
- **N-6.** Reference runs are pinned and numbered, never overwritten.
  Tracked: report.md and backlog.json only. DB and trace are gitignored.
- **N-7.** Live crawling targets only the user's own domain and the landc
  validation domain, MAX_OWN_PAGES 50, robots checked, 2 s/host, GET only.
  No competitor scraping.
- **N-8.** No fabricated regulatory identifiers. Any draft/compliance path
  refuses to run while fca_firm_ref == "000000" and says why.
- **N-9.** Hand-rank protocol is BLIND: rank the top 10 on paper from the
  report's gap list BEFORE opening the model's backlog order. Store it in
  out/backlog-handrank-<date>.md. Metric: overlap of top 5 and the position
  of each disagreement.
- **N-10.** Scoring constants change only when a recorded hand-rank
  disagreement points at them, one constant per commit, with a DECISIONS
  entry that names the disagreement.
- **N-11.** Periphery (agent, drafts, scraping) gets a dated decision, not
  a deletion, and only after Phase 5 produces own-site data.
- **N-12.** Commit policy for the CLI agent: do NOT commit or push unless
  the human says so. At each gate print `git status --short` and a proposed
  commit message, then STOP and wait.
- **N-13 (2026-11-17).** `money_kw_count` is the number of profile money
  keywords covered by the item's keyword set: `evidence["cluster_keywords"]`
  where present (order-insensitive, normalised), else the item's own
  keyword. The sitewide SCHEMA_MISSING umbrella has no keyword set, so it
  counts 0 — it is an item, not a keyword. An earlier draft counted the
  umbrella's flagged money pages instead, which made the sort key compare
  page counts against keyword counts; that was rejected so the key
  compares like with like. The umbrella remains impact-weighted by money
  pages (`money_page_count` in evidence, CRITICAL vs WARNING) — that is
  scoring, not ordering — and orders by `kind_rank` among schema-kind
  items.
- **N-14 (2026-11-17).** The N-5 NO_PAGE pre-check counts the
  ≥2-significant-token match across title + H1 + H2 combined, not within a
  single field. Rationale: the pre-check asks "does this page plausibly
  target this keyword?", and a page with one distinctive token in the
  title and another in the H1 plausibly does. Rejected alternative (per-
  field match) produces false negatives, which leave a gap as NO_PAGE
  (create a new page) when the right action is WEAK_PAGE (fix the existing
  page); a false positive merely shifts an item between two action types.
- **N-15 (2026-11-17).** The pre-check uses its own stopword set, not the
  slug-tuned `UK_MORTGAGE_STOPLIST`: `UK_MORTGAGE_STOPLIST` minus
  `mortgage`. Measured on the 74 landc target keywords: the slug list
  yields only one significant token for 11 keywords (all "mortgage"-led,
  e.g. 'mortgage advice' -> ['advice']), which would silently suppress the
  NO_PAGE -> WEAK_PAGE reclassification for the most common keyword shape.
  With `mortgage` kept, the distribution is 2 tokens x19, 3 x36, 4 x14,
  5 x5 — every keyword yields ≥2 (scratch dump: /tmp/landc_74kw_tokens.tsv,
  not committed). All other stopwords (the/a/an/uk/for/in/with/and/of/to/
  on/is/are/near/me/how/what/can/i/my/your/best) are unchanged. This list
  is for the pre-check only; slug tokenization is untouched.
- **N-16 (2026-11-17).** Phase 3 gate: the NO_PAGE pre-check reclassifies
  **5 of 31** NO_PAGE gaps on the 74-keyword landc fixture
  (`tests/fixtures/landc_audit_74kw.json`, recorded from run-20261117T153658Z):
  'how much deposit do i need for a mortgage' -> tracker-mortgages (title
  mortgage / h1 mortgage+need); 'independent mortgage broker' -> / (title
  broker+mortgage); 'mortgage affordability calculator' ->
  /mortgages/mortgage-calculator (calculator+mortgage in title and h1);
  'mortgage broker reviews' -> / (broker+mortgage); 'mortgage rates 2026' ->
  /best-mortgage-rates (title mortgage+rates). All five pages plausibly
  target their cluster under N-14; count 5 is in the plausible band (not 0,
  not 20+), so Phase 4 may proceed. One borderline case is recorded, not
  suppressed: on the clearpath own_site fixture, 'mortgage fees explained'
  reclassifies to WEAK_PAGE on /first-time-buyer via title `mortgage` + H2
  `Fees` (an H2-only second token). Accepted as N-14 as written; if the
  Phase 4 hand-rank (N-9) disagrees, tighten one constant under N-10
  (e.g. require the second token outside H2) with a DECISIONS entry naming
  the disagreement. Golden eval S01 re-based to the new deterministic output
  (top item BL-0001 meta_fix, 2.0, /first-time-buyer) and S02/S2 and
  test_gsc_demand widened/adjusted for WEAK_PAGE; each is the intended
  effect of the pre-check, recorded here rather than silently re-pinned.
- **N-17 (2026-11-17).** Hand-rank disagreement taxonomy for Phase 4 (N-9,
  N-10), decided before the hand-rank so a disagreement is interpretable.
  If the blind hand-rank EXCLUDES a pre-check-reclassified item from the
  top 10, that is a pre-check disagreement: N-10 applies to the pre-check's
  token rule (e.g. require the second token outside H2, N-16), not to
  scoring. If the hand-rank INCLUDES the item but ranks it lower than the
  model, that is a scoring disagreement: N-10 applies to the WEAK_PAGE
  impact/effort constants, not the token rule. Priority-2.0 (meta_fix
  effort) placement is a prior, not a verdict; an exclusion must not be
  "explained" as a priority complaint, and a demotion must not be
  "explained" as a match complaint. One constant per commit, DECISIONS
  entry naming which class of disagreement it answers.
- **N-18 (2026-11-17).** Phase 4 comparison baseline, measured on the
  74-keyword landc fixture AFTER Phase 3 (run-phase4-fixture-20261117,
  fixture `tests/fixtures/landc_audit_74kw.json`, deterministic, then
  discarded): SCHEMA_MISSING 27, NO_PAGE 26, WEAK_PAGE 9, LOCAL_MISSING 6;
  68 gaps total; no type above 40%; WEAK_PAGE moved 4 -> 9, consistent
  with the 5 reclassifications recorded in N-16. The Phase 4 live run's
  per-type distribution should be within ±5 of these counts, and its
  reclass count should be 5 ± 3 (the fixture is a 50-page crawl of the
  same site, so it should be near-identical). A materially different
  reclass count means the live crawl differs from the fixture (new or
  changed pages/titles); record that before the hand-rank. Do not compare
  the live run against the pre-Phase-3 baseline (31/27/6/4). E9's "at
  least 3 gap types, no type above 60%, backlog ≤ 30" still holds at
  27/68 = 39.7% max — but it is verified here against the post-Phase-3
  distribution, not assumed.
