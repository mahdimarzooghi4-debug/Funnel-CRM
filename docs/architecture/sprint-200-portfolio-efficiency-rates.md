# Sprint 200: portfolio funnel efficiency rates

The period comparison now adds three aggregate funnel rates for each selected period:

- click-through rate: clicks divided by impressions;
- click-to-lead rate: leads divided by clicks;
- lead-to-conversion rate: conversions divided by leads.

Each rate is computed from portfolio totals, rather than averaging campaign-level percentages. The API reports the number of distinct measurement days where both numerator and denominator were recorded. If the denominator is zero or either side is missing, the rate is unavailable. Changes are reported in percentage points, alongside relative percent change when the baseline is non-zero.

The rates describe the selected campaign mix and recorded data. They are not causal estimates, and should be interpreted together with period length and paired-day coverage.
