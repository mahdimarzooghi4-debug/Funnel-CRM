# Sprint 100: customer lifecycle follow-up review queue

Adds `GET /api/v1/crm/analytics/customer-lifecycle/follow-up-candidates`, a read-only worklist for marketing and sales managers. The caller selects the inactivity period and may narrow the result by current lifecycle stage, profile kind, and authorized organization unit.

Each result includes the current profile identity, latest linked CRM activity timestamp, recorded activity count, elapsed days, and the explicit reason it matched the selected rule. Active profiles with no linked CRM activity are shown separately from profiles with an older recorded activity. Missing activity means the CRM has no linked event; it does not establish that no interaction occurred.

The endpoint uses only the caller's `crm.profile:view` organization scope and writes an access audit event. It does not infer churn or causal risk, send messages, or create work items. A manager can review the evidence and use existing CRM work item flows to assign a follow-up.

The API supports stable historical review with an explicit timezone-aware `as_of` timestamp, pagination, and manager-selected inactivity days from 1 to 365. No lifecycle-stage thresholds are hard-coded.
