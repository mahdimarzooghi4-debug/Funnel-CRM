# Sprint 74: campaign-level recorded cost analysis

Add campaign-level recorded spend per lead and per conversion, compared against the equal-length prior report period for the same campaign identifier. Preserve the spend currency; do not calculate costs from missing outcomes, zero or invalid denominators, missing spend, multiple currencies, or a changed currency between periods.

Display the reason a campaign cost is unavailable and include the current value and comparison context in CSV. This is a descriptive unit-cost measure, not ROI or causal attribution.

## Validation

Initial implementation commit `e7934cc46ebbef42dfbba2f0e59bd982e74cd7c3` passed GitHub Actions run `39969705949`: 94 Python tests passed (3 existing warnings), and the budget comparison browser behavior test passed.
