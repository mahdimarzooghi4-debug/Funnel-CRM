# Sprint 68: channel period comparison

Extend the equal-length report comparison with channel-level changes for leads, conversions, and recorded spend. Preserve the same rules as the overall view: missing observations remain unknown, spend stays separated by currency, and percentage change is unavailable when the previous value is missing or zero.

Include channel-level changes and their prior/current values in the CSV. This is descriptive reporting and must not imply causal attribution to a budget scenario.

## Validation

Exact head `c8f27198874b209b1cacad6f63d42ce90dc3dbed`: GitHub Actions run `39958704107` succeeded; Alembic passed, pytest reported 94 passed with 3 warnings, and the Node client behavior test passed.
