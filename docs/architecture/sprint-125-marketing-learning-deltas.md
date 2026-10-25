# Sprint 125: compare observed marketing learning metrics

The evidence view now calculates the absolute and percentage change between baseline and follow-up actuals when both values exist and use the same unit. It shows recorded-day coverage for both periods so managers can judge how much evidence supports the comparison.

Percentage change is omitted when the baseline is zero. Missing observations or currency mismatches are labeled as not comparable. The view remains descriptive and does not attribute the observed change to the corrective action.

Validation covers positive deltas, percentage calculation, coverage display, and zero-baseline handling in the browser client test.
