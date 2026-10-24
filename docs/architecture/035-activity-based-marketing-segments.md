# Activity-based marketing audience segments

- Sprint: 28
- Related: CRM-DOM-03, CRM-DOM-06, CRM-DOM-11
- API: saved segment criteria at `/api/v1/crm/segments`

Saved live segments can now combine existing profile kind/lifecycle filters with observed customer activity:
- one or more stable activity type keys;
- one or more bounded channels;
- an optional rolling `within_last_days` window.

A preview includes a profile only when a matching activity row exists. It uses a correlated `EXISTS` query, so multiple matching activities do not duplicate customer rows. The time window is evaluated at preview time; segment membership is not materialized or cached.

All activity matching remains in the same tenant and is additionally restricted by the segment's organization subtree and the caller's effective `crm.profile:view` scope. Segment audit continues to record the matched count and pagination only; it does not copy customer names or criterion values. Segments remain audience definitions and do not enroll customers or send messages.

PostgreSQL/API tests cover matching by activity type, channel and recent time, plus a no-match case and the existing authorization/audit behavior.
