# Backlog hand-rank vs model ranking — landc.co.uk (2026-11-17)

Model ordering comes from `out/run-20261117T150656Z/backlog.json`
(priority = impact × confidence / effort, GSC boost 1.0, no GSC data attached).
Hand ranking is an SEO judgment for a UK whole-of-market mortgage broker,
weighted by revenue proximity and speed to value.

| # | Model item | Model prio | Hand rank | Hand rationale |
|---|---|---|---|---|
| 1 | BL-0001 Schema umbrella on 17 pages (3 money pages, 3 schema types) | 0.375 | 4 | Real but hygiene; impact is spread across 17 pages of which ~10 are low-value (careers, anti-slavery, complaint data). Restrict to money pages + top 5 service pages, and do it after the content gaps. Its model #1 comes from confidence 1.0, not from demand. |
| 2 | BL-0002 Create /bad-credit-mortgage | 0.3333 | 1 | High-intent commercial query, dedicated gap, no competitor covers it in the audit evidence, direct revenue relevance for an adverse-credit broker. Ship with FAQPage block and full FinancialService schema. Highest value-per-hour on the list. |
| 3 | BL-0003 Create /how-much-can-i-borrow-mortgage | 0.3333 | 2 | High-volume informational head term; classic top-of-funnel lead magnet for a broker; strong internal-link hub opportunity to remortgage / first-time-buyer money pages. |
| 4 | BL-0004 Create /remortgage-calculator | 0.3333 | 3 | Commercial calculator intent; site already has LTV, stamp-duty and mortgage calculators but no remortgage-specific one, so this is a clear gap with proven demand (site already ranks near calculator queries). |

## Agreement

- Model and hand ranking agree on the three NO_PAGE items as the actionable
  core, and on their relative order (BL-0002 > BL-0003 > BL-0004). That order is
  defensible: bad-credit (commercial) > borrow amount (informational, high
  volume) > calculator (tool intent).

## Disagreement

- Model puts schema umbrella first (BL-0001). Hand ranking puts it fourth.
  Root cause: confidence 1.0 (audit-backed) beats 0.5 (heuristic NO_PAGE) in the
  formula, but the formula has no term for "is this the *money page cluster*"
  inside SCHEMA_MISSING beyond `money_page_count`, and none of the schema
  items are demand-weighted. A human would trade a certain, low-urgency win
  for three uncertain, high-intent wins every time.
- Suggested calibration (not applied here, would need review): add a
  intent/revenue-weight for NO_PAGE on commercial clusters, or down-weight the
  sitewide SCHEMA_MISSING umbrella by non-money-page fraction. Cheaper
  alternative: leave the formula alone and split the schema umbrella item into
  "money pages first" vs "remaining pages" items at profile time.

## Caveats

- No GSC history was available, so neither ranking is demand-validated. With
  3 months of GSC, the ordering would likely change again.
- The profile was widened from 10 to 74 target keywords on 2026-11-17; a
  re-run will almost certainly add new NO_PAGE clusters (e.g. self-employed
  mortgage, 95 percent mortgage) and may change the ordering. Treat this
  comparison as a snapshot of the 10-keyword output.
- Hand ranking is one practitioner's judgment, not a validated outcome metric.
