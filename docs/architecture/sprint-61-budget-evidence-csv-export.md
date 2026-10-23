# Sprint 61: export budget comparison evidence

Add a CSV download to the budget comparison report. It includes the reporting period, scenario reconciliation by currency, campaign spend and observed lead/conversion metrics, plus per-scenario campaign allocations and same-currency variance evidence.

CSV cells are quoted with RFC-style quote escaping. String values beginning with spreadsheet formula markers are prefixed to keep them inert when opened in common spreadsheet tools. Numeric values remain numeric. The export is generated from the authorized comparison response already rendered on the page; it introduces no new API or data access path.

## Validation

Exact head `1c5173a642e572ec2f97daf4643e59932fb7edf0`: GitHub Actions run `39953525079` succeeded; Alembic passed, pytest reported 94 passed with 3 warnings, and the Node client behavior test passed.
