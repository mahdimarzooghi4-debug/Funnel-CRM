# Sprint 71: channel target status summary

Add a compact channel-and-metric roll-up to the budget comparison workspace. Count campaign target evaluator outcomes as met, not met, insufficient data, or unknown, using only campaigns common to the selected report scenarios. Keep unknown statuses distinct from insufficient observations.

Suppress aggregate rows when the authorized portfolio response is truncated; a partial page must not look like a complete channel summary. Include the same complete summary in CSV when available.

## Validation

Exact initial feature commit `1fc521d334469c1733dea8c69aba8f9c493900c2` passed GitHub Actions run `39961294935`: 94 Python tests passed (3 existing warnings), and the budget comparison browser behavior test passed.
