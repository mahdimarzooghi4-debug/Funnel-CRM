# Sprint 66: evidence coverage rates

Extend the evidence coverage view with rates as well as counts. Show each overall evidence rate as covered campaigns / overlapping campaigns and show each channel's covered count, denominator, and percentage. Include the same percentages in CSV exports so the comparison remains usable outside the dashboard.

A zero campaign denominator is displayed as unknown and exported as a blank numeric value with an explicit note; it must never appear as 0% coverage. Rates describe evidence completeness, not campaign effectiveness or performance.

## Validation

Exact head `e19b79c4b5e8e692987970bef3afd0778d093ad2`: GitHub Actions run `39956968364` succeeded; Alembic passed, pytest reported 94 passed with 3 warnings, and the Node client behavior test passed.
