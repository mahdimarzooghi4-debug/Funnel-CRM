# Sprint 105 — explicit follow-up from outcomes

## Goal

Allow a manager to turn a callback request or unsuccessful contact into one assigned customer task, using the recorded outcome as context.

## API

`POST /api/v1/crm/work-items/outcomes/{outcome_id}/follow-up`

The caller needs CRM work-item creation permission for the outcome's organization. The endpoint accepts an optional active workspace assignee, timezone-aware due date, and priority. It creates an open task for the same active customer and organization. Outcomes other than `callback_requested` and `no_contact` are rejected. Repeating the request returns the task already created for that outcome, so it does not create duplicates.

Task creation is explicit; recording an outcome alone never schedules or sends contact. Both task creation and its source outcome are audited.

## Verification

Integration coverage checks unsupported outcomes, callback task creation, customer linkage, open status, due date, and idempotent replay.
