# Sprint 222: Auditable campaign readiness decisions and follow-up

Campaign managers can record one of three decisions for a draft campaign after reviewing its readiness:

- `proceed_to_schedule`
- `request_changes`
- `hold`

The API is `POST /api/v1/crm/campaigns/{campaign_id}/readiness-review`. It requires campaign management permission and returns the readiness checklist with the latest recorded manager review. A decision includes an optional note, capped at 1,000 characters.

For `request_changes` and `hold`, the manager must include a follow-up task. The task is created in the CRM work queue, linked to the campaign, and can be assigned to an active workspace member with an optional due date and priority. Work-item creation permission is required. The review event records the task ID, and the work-item event records that it came from a campaign readiness review. Both writes occur in the same database transaction.

Each review is stored as an append-only audit event with the decision, note, readiness result, check statuses, and optional follow-up task ID. The readiness response exposes the latest event; prior decisions remain in the audit history.

Recording a review does not change campaign lifecycle status, schedule, send, or approve content. Scheduling and launch still use their existing lifecycle controls.
