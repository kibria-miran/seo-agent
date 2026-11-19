# Backlog hand-rank vs model ranking — easyfinance.uk.com (2026-11-19)

Model ordering from `out/run-20261119T111812Z/backlog.json` and the
20261119T115000Z no-LLM baseline (identical 4-item backlog, byte-same
priorities; priority = impact × confidence / effort, GSC boost 1.0, no GSC
data attached). Hand ranking is a business-owner judgment (quick wins,
revenue proximity, value per hour), not a technical-correctness pass.

The task context expected a "top-5" longlist, but the real easyfinance
profile yields only 4 backlog items, so the blind comparison covers all 4.
Blind caveat: the ranking author also read the report, so this is not a
fully blinded test; it only differentiates items the model ties.

| # | Model item | Model prio | Hand rank | Hand rationale |
|---|---|---|---|---|
| 1 | BL-0001 meta_fix `/about` ('commercial mortgage advisor') | 2.0000 | 2 | High-intent head term and the page is the natural landing for "commercial mortgage advisor". One title+H1 edit, but covers only 1 keyword. |
| 2 | BL-0002 meta_fix `/services` (8 keywords) | 2.0000 | 1 | One hour of work closes 8 keyword gaps on the money hub page. Highest value-per-hour on the list by a wide margin; brokers would do this first. |
| 3 | BL-0003 meta_fix `/services/buy-to-let` ('commercial buy to let mortgage') | 2.0000 | 3 | Single money sub-page, high intent, cheap fix; outranked only because it covers one keyword. |
| 4 | BL-0004 schema umbrella (4 pages, 3 money pages) | 0.7500 | 4 | Real hygiene win but lower urgency than closing open keyword gaps; money-page-only scope would be defensible. Same position as the model. |

## Agreement

- Both rankings put the schema umbrella (BL-0004) last. Model gives it 0.75
  via impact 3 x confidence 1.0 / effort 4; the hand rank agrees on urgency
  ordering, not because of the formula.
- The three meta_fix items are treated as the actionable core in both.

## Disagreement

- The model ties BL-0001/2/3 at exactly 2.0000 (impact 2, confidence 1.0,
  effort 1). A business owner breaks the tie by keyword breadth and page
  revenue proximity: /services hub (8 keywords) > /about (1 keyword, head
  term) > /services/buy-to-let (1 keyword, high intent). The gap formula has
  no breadth term; cluster size enters only through effort, which is already
  flat at 1 for meta_fix, so the tie is structural, not incidental.
- No CTR/position weighting exists yet (B3): GSC evidence is absent, so
  neither ranking is demand-validated. All three meta_fix items score
  identically regardless of impressions.

## Suggested calibration (not applied; needs review under DECISIONS)

- Add a cluster-breadth multiplier (or explicit tie-break) for meta_fix
  items, e.g. scale by log(1 + keywords_covered), so BL-0002-style hub
  fixes surface first without changing impact/confidence semantics.
- Once GSC data is attached (B2), verify whether the impressions tiers
  (1.1 / 1.25 / 1.5) actually re-order these three; with zero attach the
  ordering cannot move today.

## Caveats

- Hand ranking is one judgment, not a validated outcome metric (same caveat
  as the 2026-11-17 landc.co.uk comparison).
- The backlog shrank from 10 items (earlier 10-keyword demo profile) to 4
  with the real 13-keyword commercial profile; comparisons against the
  2026-11-17 document are not apples-to-apples.
- No GSC history yet: neither ranking is demand-validated. Re-run this
  comparison after exporting Queries.csv (B2).
