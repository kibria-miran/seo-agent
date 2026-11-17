# out/ — frozen reference runs

`run-20261117T143756Z/`, `run-20261117T150656Z/` and
`run-20261117T153658Z/` are pinned snapshots of the landc.co.uk live
audits (`report.md` + `backlog.json` only). They are
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

Caveat on the pinned runs: they were generated against
`profiles/landc.json` with an unverified placeholder FCA firm reference
(`fca_firm_ref: "000000"`). Any compliance-related comparison against these
runs is meaningless until that field is corrected (see `profiles/README.md`).
Ordering caveat (2026-11-17): `run-20261117T143756Z/`, `T150656Z/` and
`T153658Z/` were produced with the pre-Phase-2 backlog key (secondary key
`effort`). Phase 2 restructured the key to N-3 ((-priority, -is_money,
-gsc_impressions, -money_kw_count, kind_rank, target, keyword); money flag
before target), so the code's output ordering convention has changed since
they were generated. The affected class of items is those tied on priority
but differing on money flag or `money_kw_count` — under the old key these
fell back to `effort`, under the new key money decides before `target`.
Verified 2026-11-17 by replaying the current key over the three pinned
`backlog.json` files: no items move (every priority-tied group in these
runs is also tied or ordered identically on money flag, `money_kw_count`
and GSC demand), so their item order still matches what the code emits.
The caveat stands because of provenance, not observed divergence: N-6
forbids overwriting pinned runs, so compare them for content, treat
ordering as unverified-but-currently-identical, and do not re-pin them to
force agreement.
