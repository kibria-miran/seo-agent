# SEO GROWTH AGENT

A UK-mortgage SEO audit and content-gap tool. It audits your site with a
vendored copy of [`seoextract`](third_party/seoextract), compares what you have
against a hand-written profile of target keywords and competitors, and writes a
prioritised weekly backlog. It never edits or publishes the site and it does
not use paid APIs.

**Compliance is a lint, not a gate.** The C1–C6 checks in `compliance.py` are
pattern matching, not a compliance review; passing them does not make output
compliant with UK financial-promotion rules. Every draft must be reviewed by
a qualified adviser before publication, and so must any change this tool
suggests.

**Status: Phases 0–9 complete.** The deterministic pipeline, keyless live
sources, the 16-scenario eval harness, the budgeted LLM client, the agent
tool loop and compliance-linted draft generation (`--with-drafts`) all work;
the no-LLM path is byte-reproducible without a key. Agent mode (`--agent`) is
opt-in and needs `NVIDIA_API_KEY`. The weekly backlog is files an operator
reviews — the tool never edits or publishes the site. See
[Implemented vs remaining](#implemented-vs-remaining).

## Quickstart

Requires Python 3.10+; CI runs the test suite on Python 3.12 and 3.14.

```bash
cd seo-agent
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip install --no-deps -r requirements-seoextract.txt

# Tests: requirements-dev.txt is the hashed superset that adds pytest.
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The runtime does not require installing the fork: `src/audit_adapter.py` puts
`third_party/seoextract/` on `sys.path` and imports it directly. The separate
`requirements-seoextract.txt` exists so the fork can never be silently replaced
by a PyPI release.

### Run the demo fixture (no network, no LLM)

```bash
.venv/bin/python -m src.cli run \
  --site profiles/site.json \
  --no-llm \
  --fixture tests/fixtures/own_site_audit.json \
  --run-id run-20261116T090000Z
```

Outputs:

- `out/<run-id>/report.md` — scorecard, diffs, open gaps, ranked backlog,
  competitor/SERP placeholders, budgets.
- `out/<run-id>/backlog.json` — machine-readable backlog.
- `logs/trace.jsonl` — redacted step trace (no args, no secrets).
- `out/state/seo.db` — per-run audit, keywords, gaps and backlog for diffing.

The same `run-id`, fixture and injected clock produce byte-identical report and
backlog files. The fixture path is the only run mode that requires no network.

Run the local self-check (profile, paths, vendored audit layer, optional keys):

```bash
.venv/bin/python -m src.cli doctor
```

`doctor` exits 2 on any `FAIL`, and `WARN`s when the shipped placeholder
demo profile (domain `clearpath-mortgage.co.uk`, FCA ref `123456`) is still
present; a live run is refused against it unless `SEO_AGENT_ALLOW_DEMO_PROFILE=1`
is set or `--fixture` is used.

### Audit the real site

```bash
.venv/bin/python -m src.cli run --site profiles/site.json --no-llm
```

This performs a polite crawl of the domain in the profile: max 50 pages, 2 s
between requests to the same host, an honest user agent, and GET-only requests.
Default runs (no `--agent`) execute the deterministic pipeline; `--no-llm`
forces that same path explicitly. The opt-in `--agent` flag lets an LLM tool
loop orchestrate the stage helpers with budgeted LLM calls, one retry on a bad
proposal, loop guard and deterministic fallback; it needs `NVIDIA_API_KEY` but
never executes publish/filesystem-write operations outside `out/` and `logs/`.
`--with-drafts` writes compliance-linted markdown drafts for the top three
`create_page` / `create_local_page` backlog items after C1–C6 pass. `--agent`
without `NVIDIA_API_KEY` exits 2; `--agent --no-llm` is a usage error (exit 2).

> **Replace the placeholder profile first.** `profiles/site.json` points at
> `https://clearpath-mortgage.co.uk` (a fictional demo site) with FCA firm
> reference `123456`. Change the domain, money pages, target keywords,
> competitors, cities and FCA reference to your own values before a live run.

### Mine live sources (optional)

```bash
export SEO_AGENT_GSC_CSV=/path/to/Queries.csv   # optional; unset = skipped (dep_unmet)
.venv/bin/python -m src.cli run --site profiles/site.json --no-llm --with-sources
```

Sources are keyless and go through one `Source` interface
(`src/sources/base.py`): cache (`source|query` key, 24 h TTL), per-host 2 s
throttle, honest user agent, GET-only, and an injection scrub that drops
untrusted items carrying marker phrases. A missing requirement is logged as
`dep_unmet` and skipped; it never fails the run.

Two endpoints are undocumented HTML/JSON surfaces rather than sanctioned
APIs: `suggestqueries.google.com` and `html.duckduckgo.com/html/`. They are
HTML scrapes that can break without notice (a site redesign silently yields
0 SERP rows, which this tool treats as "no SERP", not as an error) and whose
use is a terms-of-service judgement call for you to make. They are used at
low volume with a 2 s per-host throttle and an honest user agent and are not
robots-checked by design (search endpoints are not page crawls). If that
trade-off is unacceptable to you, run without `--with-sources`; no ranked
output depends on them.

| Source | Endpoint | Data |
|---|---|---|
| Google Suggest | `suggestqueries.google.com` | autocomplete candidates per seed |
| DuckDuckGo HTML | `html.duckduckgo.com/html/` | top-10 organic results per query |
| DuckDuckGo HTML (`site:`) | `html.duckduckgo.com/html/` | competitor discovery for coverage evidence |
| GSC CSV | local file / `SEO_AGENT_GSC_CSV` | clicks, impressions, CTR, position per query |
| GSC pages mapping | local file / `SEO_AGENT_GSC_PAGES_CSV` | query→page attribution (e.g. Pages export or a two-column CSV prepared from the free Search Console API) |

SERP matches are evidence: a `NO_PAGE` gap backed by both keywords and SERP
results moves from single-source (0.50) to dual-source (0.65) confidence,
which feeds the priority formula. The default (`--no-llm`, no flag) run is
unchanged and byte-identical for the same run-id, fixture and clock; live
sources are strictly opt-in.

### Eval harness (S01–S16)

```bash
.venv/bin/python -m src.cli evals          # run every scenario, exit 1 on failure
.venv/bin/python -m src.cli evals --list   # list scenarios only
```

Each scenario is a JSON file in `evals/scenarios/` (`kind` from a small
vocabulary in `src/evals.py`). Coverage: the golden baseline, clean-site gaps,
the compliance gate (C1, C2, C5, negation), the injection corpus, frozen
budgets, money-keyword impact, confidence weights, stale-run abort, byte-identical
rerun, backlog cap/order, FCA validation, the two-run diff and the
`COMP_COVERS` path. Scenarios fail as reported results — a broken checker
never crashes the harness. Results are written to `evals/results/`
(gitignored); `evals/baselines.json` is committed and is the regression
anchor for the deterministic fixture run.

### Agent mode (Phase 6, opt-in)

```bash
export NVIDIA_API_KEY=nvapi-...
.venv/bin/python -m src.cli run --site profiles/site.json --fixture tests/fixtures/own_site_audit.json --agent
```

The agent is deliberately narrow: **the LLM proposes, code decides.** Each
turn, the LLM returns one JSON proposal (`{"tool": ..., "args": {...}}` or
`{"finish": true}`). Code parses, validates (`validate_args`), executes a thin
deterministic wrapper, and feeds a scrubbed observation back. Frozen
behaviour:

- two consecutive failing proposals → deterministic template fallback (D-12);
- the same `(tool, args)` pair twice consecutively trips the loop guard;
  repeats with new args are allowed;
- LLM calls, steps, tokens and wall-clock all count against the D-13
  budgets; hitting one falls back to the template, never to a silent fail;
- observations never contain raw HTML, and injection-bearing strings are
  replaced with `[dropped:untrusted]` before the LLM sees them (D-4);
- every run persists audit/keywords/gaps/backlog to the snapshot DB and a
  trace with hashed args (D-15).

`--agent --no-llm` is a usage error (exit 2). Without a key, agent mode
exits 2 with a message naming `NVIDIA_API_KEY`.

### Compliance-gated drafts (Phase 7)

```bash
.venv/bin/python -m src.cli run --site profiles/site.json --no-llm --with-drafts --fixture tests/fixtures/own_site_audit.json
```

Drafts land in `out/<run-id>/drafts/*.md` — files for a human editor, never
published by the tool. The **compliance lint (C1–C6) runs before any draft is
written** — and passing it does not make a draft compliant:

- `--no-llm --with-drafts`: deterministic skeleton with every mandatory UK
  disclosure baked in (risk warning, FCA firm reference, fee disclosure).
  Byte-stable for the same run/fixture/clock.
- `--agent --with-drafts`: the LLM proposes copy, the lint decides whether it
  is acceptable to write at all (D-2). One retry with the violations fed back;
  still failing → the item is rejected, nothing is written, and
  `compliance_reject` is logged. Neither path makes copy compliant; a
  qualified adviser must review it before publication.

Backlog items of kind `create_page` / `create_local_page` are eligible; the
top three are drafted. Drafts are plain markdown with the firm's FCA
reference and the repossession warning — never published by the tool (D-7).

## Profile format

`profiles/site.json` is a plain JSON object:

```json
{
  "domain": "https://example.co.uk",
  "money_pages": ["/", "/free-mortgage-advice", "/remortgage"],
  "target_keywords": ["free mortgage advice", "remortgage calculator"],
  "competitors": ["moneysavingexpert.com", "habito.com"],
  "cities": ["London", "Manchester"],
  "fca_firm_ref": "123456"
}
```

- `domain` must be `https://`.
- `money_pages` must be root-relative and non-empty. Money keywords are derived
  from their slugs (`/free-mortgage-advice` → `free mortgage advice`), so the
  CRITICAL impact rule only applies to pages that actually earn revenue.
- `target_keywords` are lower-cased and de-duplicated.
- `competitors` are hostnames, not URLs.
- `fca_firm_ref` must be six digits.
- Set `SEO_AGENT_CONTACT` so the user agent carries a real contact address.

## Sample report excerpt

From `out/run-20261116T090000Z/report.md`:

```markdown
## Scorecard

- Site score: **87.5** (B)
- Pages crawled: 6
- Issues: 7 total · 1 critical · 5 warning · 1 info
- Keywords mined: 10
- Gaps open: 5
- Backlog items: 5

## Top backlog

Showing 5 of 5 items, highest priority first.

BL-0001. **Create a local page for 'mortgage advice manchester'**
   - priority `0.4333` · impact 2 · confidence 0.65 · effort 3
   - kind `create_local_page` · target `/mortgage-advice-manchester` · status `open`
```

Priorities are `(impact × confidence) / effort`, capped at 30 items, with
stable tie-breaks so the same inputs always produce the same order.

## Safety model

These are enforced in code, not by prompting:

- **Untrusted web text.** Fetched pages are data. HTML comments, `data-*`
  attributes, scripts/styles and tags are stripped; NFKC, homoglyph folding,
  zero-width removal and case folding expose hidden markers. A hit drops the
  whole text and logs `injection_attempt`. Raw HTML never reaches the LLM.
- **Compliance lint.** UK mortgage claims (approval guarantees, “no fees”,
  misleading rate claims, missing risk warnings) are pattern-matched before
  any public-facing draft is written. It is negation-aware for C1/C1b/C6 but
  it is a lint, not a compliance review, and it does not make output
  compliant — a qualified adviser must review before publication.
- **Budgets.** Exactly 12 steps, 20 LLM calls, 20k tokens in, 5k out, 180 s of
  LLM time, 120 fetches, 600 s total and 30 backlog items. The deterministic
  path uses zero LLM calls.
- **Filesystem and HTTP.** The app writes only under `out/` and `logs/`; the
  SQLite snapshot lives at `out/state/seo.db`. HTTP is GET-only except the
  single LLM POST. Secrets are redacted from the trace.
- **Human in the loop.** The agent produces files. It never edits or publishes
  the site.

## Weekly schedule

Run every Monday at 06:00 with cron, keeping the log under `logs/`:

```cron
0 6 * * 1 /opt/seo-agent/scripts/weekly.sh
```

Or with a systemd timer (installs the same `scripts/weekly.sh`):

```ini
# /etc/systemd/system/seo-agent.service
[Unit]
Description=SEO growth agent weekly run
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/seo-agent
ExecStart=/opt/seo-agent/scripts/weekly.sh
```

```ini
# /etc/systemd/system/seo-agent.timer
[Unit]
Description=Run the SEO agent every Monday

[Timer]
OnCalendar=Mon *-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

The SQLite snapshot means each run can report issues and gaps closed since the
previous one.

## Implemented vs remaining

| Phase | Area | Status |
|---|---|---|
| 0 | Repo skeleton, vendored `seoextract`, capability probe | done |
| 1 | Deterministic audit → gaps → backlog → report, no-LLM mode | done |
| 1 | Compliance rules C1–C6, schema generator, SQLite store, trace redaction | done |
| 1 | Injection filter and payload corpus | done |
| 1 | Fixture tests S1, S2, S15, S16 and safety invariants | done |
| 2 | Live sources (`suggest`, `serp`, `fetch`, `gsc_csv`), cache + throttle, opt-in `--with-sources` | done |
| 3 | Competitor discovery (`site:` search), page parsing (title/H1–H6/word count/JSON-LD schema), `COMP_COVERS` gaps | done |
| 4 | Eval harness: 16 scenarios (`evals/scenarios/`), committed baseline, `seo-agent evals` | done |
| 5 | LLM client (NVIDIA NIM), retry, strict D-13 budget ledger, redacted trace | done |
| 6 | Agent tool loop (`agent.py`) — proposes, code decides; deterministic fallback | done |
| 7 | Compliance-gated drafts (template + LLM paths, C1–C6 gate before any write) | done |
| 8 | Weekly scheduling (cron + systemd script), operational `doctor` check | done |
| 9 | README, hashed requirements, provenance | done |

All live sources sit behind one `Source` interface with cache and throttle.
Sections that have no data in a given run (e.g. no GSC export configured)
are explicitly empty in the report rather than invented.

## Repository layout

```text
src/
  audit_adapter.py   only module that imports seoextract
  compliance.py      C1–C6 claim gate
  backlog.py         priority formula, tie-breaks, cap
  gap.py             NO_PAGE / WEAK_PAGE / LOCAL_MISSING / SCHEMA_MISSING / COMP_COVERS
  schema_gen.py      schema.org JSON-LD generation from audited page data
  keywords.py        normalisation, intent, clustering
  pipeline.py        deterministic end-to-end path (+ opt-in live sources)
  report.py          markdown and backlog writers
  security.py        prompt-injection filter
  store.py           SQLite snapshots, diffs and TTL cache
  trace.py           redacted JSONL trace
  evals.py           S01–S16 scenario harness (runner for evals/scenarios/)
  llm.py             NVIDIA NIM client: retry, D-13 budget ledger, redacted trace
  agent.py           Phase 6 tool loop: LLM proposes, code decides, template fallback
  drafts.py          Phase 7 drafts: template skeleton or LLM copy, gated before write
  sources/           fetch (polite GET + robots), base Source interface,
                     suggest, serp, gsc_csv, competitor (site: discovery +
                     coverage parsing) — keyless, D-3
profiles/site.json   your site profile (demo values must be replaced)
tests/               pytest suite, factories and the golden audit fixture
evals/               injection payloads, banned claims, scenarios
third_party/         vendored seoextract + PROVENANCE.md
```

## Documentation

- `DECISIONS.md` — frozen decisions D-1..D-15 and forced revisions R-1..R-3.
- `CHANGELOG.md` — implementation history.
- `third_party/PROVENANCE.md` — upstream URL, commit, hashes and edit policy.
