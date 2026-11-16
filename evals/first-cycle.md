# First cycle — <site> — started <YYYY-MM-DD>

Goal (F-8): measure whether applied backlog items from this tool move GSC
performance, not whether the backlog was generated. Fill this in BEFORE any
site change, and only touch the site after a human (and compliance) review of
each item.

## Cycle 0 — baseline (record before any change)

Exports to attach to this file (GSC → Queries.csv, and the Pages report if the
site gets one): `gsc-queries-YYYY-MM-DD.csv`, `gsc-pages-YYYY-MM-DD.csv`.

| date | query | page | impressions | clicks | CTR | avg position |
| --- | --- | --- | --- | --- | --- | --- |
| YYYY-MM-DD | <target keyword> | <if known> | | | | |

One row per target keyword, at minimum every money keyword from the profile,
plus the top 20 by impressions. Branded queries listed separately.

- Baseline source: <file names / GSC date range>
- Tool baseline artefact: <path to out/<run-id>/report.md>
- Site-wide notes at baseline: <score, gaps open, backlog items>

## Change log (one row per applied backlog item, dated)

| date applied | backlog item id | kind | page | change made | reviewed by |
| --- | --- | --- | --- | --- | --- |
| YYYY-MM-DD | BL-XXXX | create_page | /target | <what was changed> | <adviser name> |

Rules:
- no item is applied before its review row is filled;
- one row per change; site changes not produced by this tool are logged too;
- dates are absolute, UTC, `YYYY-MM-DD`.

## Re-check (4–6 weeks after each change)

| date | query | page | impressions | clicks | CTR | avg position | delta vs baseline |
| --- | --- | --- | --- | --- | --- | --- | --- |

- Per-item verdicts: <which items moved the metric, which did not, unknown>
- Confounds noted: <algorithm updates, seasonality, other work, GSC export
  sampling limits>
- Net decision: <keep / iterate / revert items based on the evidence>

## Success metric (agreed before work starts)

- Primary: <e.g. clicks for money keywords up X% vs baseline after 4–6 weeks>
- Guardrail: <no drop in rankings/CTR for non-target pages>
