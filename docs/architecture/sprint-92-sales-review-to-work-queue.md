# Sprint 92: sales review to work queue

Managers can convert a selected set of opportunities from a target review into regular CRM work items in one request. This connects the target/funnel review to the existing assignable work queue without creating a second task system.

The operation is explicit and scoped:
- Caller needs target view, opportunity view, and work item create permission for the target organization.
- Every selected opportunity must belong to the target's tenant, organization, and pipeline; be in an open stage; and have either no expected close date or one within the target period.
- The request selects up to 50 unique opportunities and supplies the title prefix, priority, optional active assignee, description, and due date.
- Each created task links to its opportunity and emits an audit event with the originating target ID.

Endpoint:
- `POST /api/v1/crm/work-items/from-sales-review`

No task is created until a user explicitly submits the selection. Existing work-item lifecycle and assignment rules apply.
