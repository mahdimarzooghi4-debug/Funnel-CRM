# Sprint 76: objective-level budget reconciliation

Add a read-only marketing decision view that groups scenario allocations by campaign objective, scenario, and currency. It shows planned budget, the planned amount covered by comparable recorded spend, comparable observed spend, variance, and allocation coverage.

Only API-provided spend and variance in the allocation currency are comparable. Missing or currency-mismatched actuals remain unknown, currencies are not converted, and a group with no comparable allocations does not display actual spend or variance as zero. The same summary is included in CSV export.

## Validation

Pending exact-head CI.
