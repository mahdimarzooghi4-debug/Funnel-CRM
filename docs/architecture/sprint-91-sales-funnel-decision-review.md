# Sprint 91: sales funnel decision review

The target-aligned forecast now has a read-only review workspace for diagnosing target risk. For each authorized target, it groups current open opportunities by configured pipeline stage and reports stage counts, priced counts, gross value, weighted value, and missing-value/probability counts.

The review list flags objective conditions that call for human review: missing amount or target currency, missing stage probability, missing expected close date, a past expected close date, and an unconfigured stage. It does not prescribe outreach, alter an opportunity, or assign responsibility.

This endpoint requires both target-view and opportunity-view access in the target's organization scope. It reports only target currency values, does not convert amounts, and caps loaded opportunities per target at 2,000 and visible review entries at 100; counts reflect the loaded, capped set.

Endpoint:
- `GET /api/v1/crm/sales-targets/decision-review`

Integration coverage verifies stage aggregation, overdue flagging, and currency isolation alongside the target-aligned forecast math.
