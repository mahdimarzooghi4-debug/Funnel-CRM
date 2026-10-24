# Sprint 97: connect marketing corrective actions to CRM work

Adds an optional, manager-triggered action on a marketing learning review that creates a CRM work item linked to the same campaign and review. The task carries the complete corrective action and assessment in its description, with manager-selected assignee, due date, and priority. The source review link is persisted and unique per tenant, and the operation locks the review before checking/creating so repeated requests return the existing task instead of duplicating it.

The change adds a nullable provenance field to CRM work items, a tenant-scoped foreign key and uniqueness constraint, and an Alembic migration. Normal CRM work items remain unaffected. The new action requires both campaign-management and work-item-create permissions; active workspace membership is required for an assignee. Task creation and review linkage are audited.

Integration coverage verifies authorized creation, assignment metadata, task-list visibility, repeat-call idempotency, persisted source linkage, and audit records.
