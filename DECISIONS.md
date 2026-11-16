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
| D-6 | Compliance gate (`compliance.py`) runs before any public-facing draft is written. | frozen |
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

## Implementation notes (not revisions)

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
- Draft generation is gated before the write, never after: the deterministic
  path uses a disclosure-complete template (byte-stable); the agent path lets
  the LLM propose and the gate decide, with exactly one feedback retry. A
  template that fails the gate is dropped, not shipped — the gate is the
  authority in both modes. Drafts are written once per run; the idempotent
  completion path never re-spends LLM budget on copy that already exists.

See `CHANGELOG.md` for dates and context.
