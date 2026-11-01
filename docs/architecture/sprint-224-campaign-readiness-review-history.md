# Sprint 224: Campaign readiness decision history

The campaign API exposes paginated review history at:

`GET /api/v1/crm/campaigns/{campaign_id}/readiness-reviews?limit=20&offset=0`

Entries are ordered newest first and retain the decision, manager note, reviewer, review time, readiness outcome, and per-check status snapshot recorded at decision time. Follow-up task ID, current status, assignee, and due date are resolved from the work queue when the caller has `crm.work_item:view` in the campaign scope. Without that permission, review decisions remain visible to campaign viewers while every follow-up field is null.

The endpoint accepts page sizes from 1 to 100 and returns total count and `has_more`. Viewing review history is audited. The review records remain append-only even as linked work items change.
