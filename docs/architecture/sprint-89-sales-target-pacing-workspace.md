# Sprint 89: sales target pacing workspace

This increment completes the manager workflow for sales targets and adds an in-period pacing view:

- Managers can revise target amount, currency, or period within the existing tenant and organization scope.
- Performance returns a calendar-day prorated target-to-date, current won-stage amount due by the as-of date, variance, pace status, and a month-by-month view.
- The report keeps every currency separate and allows an explicit as-of date so historical snapshots can be reproduced.

The pace comparison uses linear calendar-day prorating. It is a management signal, not a seasonal forecast or a cash-collection statement. The underlying actuals are opportunities currently in a configured won stage, grouped by expected close date; the report labels that basis explicitly.

Endpoint additions:
- `PATCH /api/v1/crm/sales-targets/{target_id}`
- `GET /api/v1/crm/sales-targets/performance?as_of_date=YYYY-MM-DD`
