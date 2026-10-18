# Customer activity analytics

- Sprint: 29
- Related: CRM-DOM-11
- Route: `GET /api/v1/crm/analytics/customer-activities/summary`

The manager summary compares two adjacent equal-length windows. For `window_days = N`, the current interval is `[now - N days, now)`; the previous interval is `[now - 2N days, now - N days)`.

It reports:
- count of recorded activity rows per interval;
- count of distinct active, non-merged CRM profiles with at least one activity;
- activity-count percentage change, null when the previous count is zero;
- activity counts grouped by channel and stable activity type.

All queries apply tenant and effective `crm.profile:view` organization scope in SQL. An optional organization selector must independently pass the same scope check. Audit rows keep only the period length and aggregate counts.

These are counts of events delivered to CRM. They do not measure revenue, campaign attribution, conversion, or the full market; missing or disconnected product events are not imputed. Results contain no customer-level records.
