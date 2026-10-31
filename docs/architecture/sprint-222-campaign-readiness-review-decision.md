# Sprint 222: Auditable campaign readiness decisions

Campaign managers can record one of three decisions for a draft campaign after reviewing its readiness:

- `proceed_to_schedule`
- `request_changes`
- `hold`

The API is `POST /api/v1/crm/campaigns/{campaign_id}/readiness-review`. It requires campaign management permission and returns the readiness checklist with the latest recorded manager review. A decision includes an optional note, capped at 1,000 characters.

Each review is stored as an append-only audit event with the decision, note, readiness result, and status of each readiness check. The readiness response exposes the latest event; prior decisions remain in the audit history.

Recording a review does not change campaign lifecycle status, schedule, send, or approve content. Scheduling and launch still use their existing lifecycle controls.
