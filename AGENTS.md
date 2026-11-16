# AGENTS.md

Guidance for LLM agents working in the `seo-agent` repository (UK-mortgage SEO
growth agent: audit → keyword gap analysis → prioritised weekly backlog).

Read `README.md` for the full feature tour and `DECISIONS.md` for the frozen
decision log (D-1..D-15, forced revisions R-1..R-3). Frozen decisions are
bending-point invariants enforced by tests, not style preferences.

## Essential commands

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip install --no-deps -r requirements-seoextract.txt   # vendored fork, never from PyPI
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt    # adds pytest

.venv/bin/python -m pytest -q                 # default: -m 'not slow and not live'
.venv/bin/python -m src.cli run --site profiles/site.json --no-llm \
  --fixture tests/fixtures/own_site_audit.json --run-id run-<fixed>          # deterministic, no network/LLM
.venv/bin/python -m src.cli evals            # frozen v1.2 eight; exit 1 on failure
.venv/bin/python -m src.cli evals --all       # frozen eight + evals/extra/ (16)
.venv/bin/python -m src.cli evals --list
```

- Python 3.10+ required; CI runs the suite on 3.12 and 3.14.
- Test markers (see `[tool.pytest.ini_options]`): default suite excludes `slow`
  and `live`; the 2 deselected are both `live` tests in `tests/test_live.py`
  (one real NVIDIA NIM call; require `NVIDIA_API_KEY`). There are no `slow`-marked
  tests. Expect 447 passed, 2 deselected, on 3.12 and 3.14.
- `pyproject.toml` declares `[tool.ruff]` (line-length 100, py310) but no lint
  script is wired; tests are the gate.
- `--agent` needs `NVIDIA_API_KEY`; `--agent --no-llm` is a usage error (exit 2).
- Writes are allowed only under `out/` and `logs/` (D-15, enforced by tests).

## Non-obvious architecture

- **D-1: `src/audit_adapter.py` is the ONLY module allowed to import `seoextract`
  (vendored at `third_party/seoextract/`, pinned commit `6544a74...`).** It
  prepends the vendor dir to `sys.path`; nothing from PyPI is installed at
  runtime. The import-time capability probe (`probe_capabilities`) raises
  `ImportError` naming missing symbols. R-1: real API lives in
  `seoextract.models` (`AuditResult`, `PageData` with `meta_description` and
  `h1_tags`, not `meta_desc`), not the package root. R-2: probe runs only when
  the vendored package is importable. R-3: D-15 supersedes HEAD, broken links
  use GET. Do not edit `third_party/**`; see `third_party/PROVENANCE.md` for
  the patch policy.
- **D-2: LLM proposes, code decides.** Agent mode (`src/agent.py`): each turn
  the LLM returns one JSON object (`{"tool": ..., "args": {...}}` or
  `{"finish": true}`). Code validates via `validate_args` against a per-tool
  `args_schema`, executes a thin wrapper, feeds a scrubbed observation back
  (`_dump`, max 900 chars). A failing proposal is retried **once**; two
  consecutive failures → deterministic template fallback (`_ensure_complete`
  calls the same tools). The loop guard trips only on the SAME `(tool, args)`
  pair twice consecutively; repeats with new args are allowed (a test enforces
  this distinction; conftest documents it).
- **D-12: `--no-llm` is fully deterministic, zero LLM calls.** `src/pipeline.py`
  is the reference path; agent tools are wrappers over pipeline helpers.
- **D-9/D-10: idempotence and time.** Same `run_id` + fixture + injected clock
  → byte-identical `report.md`/`backlog.json` (report body is timestamp-free;
  timestamp goes through `clock.now()`). Tests must monkeypatch `clock.now`,
  never `datetime.now()`. Cache keys are `source|query` with `ttl_seconds`,
  not calendar dates.
- **D-13: budgets enforced in code**, not prompts: 12 steps / 20 calls / 20k in /
  5k out / 180 s LLM / 120 fetches / 600 s total / 30 backlog cap
  (`src/config.py`). LLM budgets count **per attempt**, including retries;
  over-budget prompts are rejected pre-spend via chars/4 estimate; if server
  omits `usage`, the estimate reconciles the ledger. `LLMClient` passes
  `max_retries=0` to the OpenAI SDK so retries flow through our ledger.
- **D-4: fetched web text is untrusted.** HTML stripped, NFKC + homoglyph
  folding + zero-width removal + casefolding (`src/security.py`), markers drop
  the item and log `injection_attempt`; raw HTML never reaches the LLM. Agent
  observations go through `scrub_value` → `[dropped:untrusted]`.
- **D-14: tool registry** (`build_registry()`) tools declare `requires=[]`
  (env var names). Unmet requirement → skipped and logged `dep_unmet`, never
  raised; a skip does NOT count as a proposal failure. Only `GSC_CSV` uses
  `requires=("SEO_AGENT_GSC_CSV",)` today. GSC cache key fingerprints the
  export (name/size/mtime), not a fixed query, so a refreshed export is not
  served stale. `check_compliance` demonstrates the pattern, kept empty by
  design.
- **Placeholder guard.** `src/cli.py` refuses a live (non-fixture) run when
  the profile still carries clearpath-mortgage.co.uk + FCA 123456, unless
  `SEO_AGENT_ALLOW_DEMO_PROFILE=1`. `doctor` PASSes the profile but WARNs on
  the placeholder. Fixture runs are unaffected.
- **D-6: compliance lint (`src/compliance.py`, C1–C6; pattern matching, not a
  compliance review) runs BEFORE any draft
  write** in both modes. Deterministic path: disclosure-complete template,
  byte-stable. Agent path: one feedback retry, then `compliance_reject`,
  nothing written. Only `create_page` / `create_local_page` items are eligible,
  top 3 drafted. Drafts are never published.
- **Compliance rules** (all negation-aware via `_is_negated`, 90-char window,
  same-sentence): C1 banned absolutes (from `evals/banned_claims.json` +
  `config.BANNED_CLAIMS`), C1b bare "no fees" w/o disclosure, C2 "free" w/o
  disclosure, C3 repossession warning on mortgage content, C4 FCA 6-digit firm
  reference, C5 rate/APR claim w/o "representative example", C6 invented social
  proof. `check_text` is pure code, never calls an LLM.
- **D-15: writes only under `out/` and `logs/`** (enforced by
  `assert_write_paths_under` in conftest). Default DB is `out/state/seo.db`,
  cache is `out/cache/`; `--db`/`--out` are explicit overrides. HTTP is
  GET-only except the single LLM POST.
- **Sources** (`src/sources/base.py`): one `Source` interface, fixed order:
  requirements → TTL cache → fetch (throttled, 2 s/host, honest UA, GET) →
  injection scrub. Errors raise `SourceError` into the pipeline which logs and
  skips. Untrusted-text keys scanned: `keyword|title|snippet|text`. Sources
  are off by default: `--with-sources` enables only the file-based GSC ingest
  (`gsc_csv`: Queries.csv demand keywords; `gsc_pages`:
  `SEO_AGENT_GSC_PAGES_CSV` query→page map, surfaced as `gsc_pages` evidence
  in gaps). `--with-scraping` opts in to the ToS-grey Suggest/SERP scraping
  and competitor discovery. The default path never touches the network. GSC
  exports are fingerprinted (name/size/mtime) as cache key. Search/API
  endpoints are NOT robots-checked by design; page crawls are. ddgs was
  removed 2026-11-16 (declared but never wired; the HTML endpoints are used
  directly).
- **Report safety header.** `render_report` emits a first-block disclaimer:
  compliance is a lint, not legal/financial advice, and a qualified adviser
  must review before publication. Do not remove it; it is load-bearing for
  the v1.2 review's F-4.
- **Store** (`src/store.py`): SQLite, WAL + FK + 5 s busy timeout; caller
  groups writes into transactions. `mark_running_as_aborted(except_run_id=...)`
  on start makes half-written/crashed runs show as `aborted`, never `ok`.
  Diffs computed in code. Severity etc. mirror vendored enums.
- **Trace** (`src/trace.py`): append-only JSONL `logs/trace.jsonl`. Args are
  never stored raw — `args_hash()` stores a 16-hex sha256 of redacted sorted
  args; sensitive key names and `nvapi-`/`sk-`/`Bearer`-shaped strings are
  redacted. Tests/metrics read this, not a debug log.
- **Evals** (`src/evals.py` + `evals/scenarios/*.json`): small `kind`
  vocabulary (`golden_baseline`, `compliance_text`, `injection_corpus`,
  `budget_constants`, `money_impact`, `confidence`, `aborted_run`,
  `byte_identical_rerun`, `backlog_cap_and_order`, `profile_validation`,
  `two_run_diff`, `competitor_gap`, ...). Scenarios are reported, never raised;
  results to `evals/results/` (gitignored); committed anchor is
  `evals/baselines.json`. Pinned clock for determinism.

## Conventions & gotchas

- Config values must come from `src/config.py` — modules must not hard-code
  budgets, city lists, weights, disclosure phrases. No timestamps created there.
- Money keywords derive from `money_pages` slugs (homepage `/` excluded); do not
  treat the whole target list as money or the CRITICAL impact rule is meaningless.
- `SiteProfile` validation: `domain` must be `https://`, `money_pages`
  root-relative non-empty, target keywords lowercased+de-duped, competitors are
  hostnames not URLs, `fca_firm_ref` exactly 6 digits, `cities` ⊆ `UK_CITIES`
  (case-insensitive). Placeholder profile points at a fictional demo site with
  `fca_firm_ref` `123456` — replace before live runs. `SEO_AGENT_CONTACT` sets
  the contact in the UA.
- Tests: factories in `tests/conftest.py` default every field — pass
  `**overrides` to change one thing. `FakeLLM` pops one canned response per
  call and `pytest.fail`s if the test under-staged; a response may be an
  exception instance. Two bad proposals must be staged because the agent
  retries once before fallback. `inject_fixture` monkeypatches
  `audit_adapter.DEFAULT_FIXTURE_PATH`. `_inject_clock`-style fixtures patch
  `clock.now`. `assert_write_paths_under()` guards D-15.
- `requirements-seoextract.txt` uses `--no-deps` deliberately so the fork can
  never be replaced by a PyPI release. `requirements(-dev).txt` are hashed;
  use `--require-hashes`.
- Eval scenario `kind`s must stay within the fixed vocabulary in `src/evals.py`
  — adding a new one means touching both.
- Adding a live source: subclass `src/sources/base.Source`, set `name` (cache
  key prefix), optionally `requires`/`ttl_seconds`, implement `fetch()` only
  (never the cache/scrub logic) and add `to_<model>()` helpers; wire it in
  `pipeline.mine_live_sources`. Candidates with untrusted text must flow
  through `Source._scrub`, i.e. return dicts with the text keys.
- Do not re-export seoextract names elsewhere; upstream renames must break
  exactly one file and its probe test.
- Target keywords are lower-cased and de-duplicated; clusters use
  `JACCARD_THRESHOLD=0.6`; `UK_MORTGAGE_STOPLIST` deliberately keeps
  "remortgage" (head term to match in title/H1).
- `out/run-20261116T090000Z/` in the tree is a sample committed output, not
  build artefacts to edit.
- `.crush/`, `.pytest_cache/` are tool state; `out/` (except the sample) and
  `logs/`, `evals/results/` are gitignored runtime artefacts.

## Repo layout quick map

`src/` — pipeline, agent, LLM client, compliance, gap/keywords/backlog logic,
models (pydantic), store/trace/evals, `sources/` (keyless). `tests/` — pytest
suite, golden audit fixture in `tests/fixtures/own_site_audit.json`.
`evals/` — scenarios, baselines, banned claims, injection payloads.
`profiles/site.json` — demo profile (replace before live use).
`DECISIONS.md`, `CHANGELOG.md`, `third_party/PROVENANCE.md` — decision and
provenance records; update `CHANGELOG.md` for any spec-affecting change.
