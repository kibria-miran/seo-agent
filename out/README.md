# out/ — frozen reference runs

`run-20261117T143756Z/` and `run-20261117T150656Z/` are pinned snapshots of
the landc.co.uk live audits (`report.md` + `backlog.json` only). They are
documentation baselines for future comparison, not live output, and they are
not regenerable from the current state: the crawl database (`out/state/seo.db`)
and the trace logs are gitignored, so re-running the crawl would not reproduce
these files byte for byte.

Convention:

- `run-20261117T160000Z/` is **evidence, not a baseline**: a synthetic
  fixture payload (clearpath-shaped audit pages, all fetches latency 0, audit
  source cache) written through the live DB path under a landc-labelled run
  row. Phase 1 (2026-11-17) proved the suspected cross-domain delta came from
  this corrupted row, not from baseline selection. It is kept only as the
  reproduction artifact; never use it as a comparison reference.
- New live runs create new `out/<run-id>/` directories. Do not overwrite or
  delete a pinned run.
- Only `report.md` and `backlog.json` are committed; the DB, traces, caches
  and drafts stay untracked.
- A run is pinned here only when it is meant as a reference baseline, and this
  file is updated to list it. The test suite's baseline fixture lives in
  `tests/fixtures/landc_audit.json`, not here.

Caveat on both pinned runs: they were generated against
`profiles/landc.json` with an unverified placeholder FCA firm reference
(`fca_firm_ref: "000000"`). Any compliance-related comparison against these
runs is meaningless until that field is corrected (see `profiles/README.md`).
