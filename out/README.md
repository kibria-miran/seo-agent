# out/ — frozen reference runs

`run-20261117T143756Z/` and `run-20261117T150656Z/` are pinned snapshots of
the landc.co.uk live audits (`report.md` + `backlog.json` only). They are
documentation baselines for future comparison, not live output, and they are
not regenerable from the current state: the crawl database (`out/state/seo.db`)
and the trace logs are gitignored, so re-running the crawl would not reproduce
these files byte for byte.

Convention:

- New live runs create new `out/<run-id>/` directories. Do not overwrite or
  delete a pinned run.
- Only `report.md` and `backlog.json` are committed; the DB, traces, caches
  and drafts stay untracked.
- A run is pinned here only when it is meant as a reference baseline, and this
  file is updated to list it. The test suite's baseline fixture lives in
  `tests/fixtures/landc_audit.json`, not here.
