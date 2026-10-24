# Sprint 93: sales target execution review

This increment adds a target-level summary of execution activity from the existing CRM work queue. It reports task counts by lifecycle state, overdue active tasks, active tasks without an assignee, workload by membership ID, opportunity follow-up coverage, and a compact task detail list.

The report is read-only and requires target, opportunity, and work-item view permission in the target organization. It includes opportunities whose expected close date is in the target period plus unscheduled opportunities in the target currency. Work items are linked through those opportunity records; no parallel task storage is introduced.

Limits: up to 250 targets, 2,000 matching opportunities per target, and 100 task details per target. Aggregated task counts operate across all tasks linked to the loaded opportunity set. An explicit as-of date makes overdue counts reproducible.

Endpoint:
- `GET /api/v1/crm/sales-targets/execution-review`
