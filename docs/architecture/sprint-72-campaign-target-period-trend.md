# Sprint 72: campaign target status period comparison

Compare target evaluator status for the same campaign and metric across the current report period and its equal-length preceding period. Use exact-period target portfolio evaluations and only campaigns included in the selected budget comparison.

Show transitions as descriptive counts, including missing target plans and insufficient observations as distinct states. If either portfolio response is unavailable or truncated, suppress the aggregate comparison rather than present partial counts. Carry the transitions into CSV.

## Validation

Initial feature commit `29a245c9df9a0616322bd73b8b55e6c7b9751f35` passed GitHub Actions run `39968292913`: 94 Python tests passed (3 existing warnings), and the budget comparison browser behavior test passed.
