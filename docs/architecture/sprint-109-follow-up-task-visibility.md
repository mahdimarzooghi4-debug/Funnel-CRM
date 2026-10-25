# Sprint 109: Lifecycle follow-up task visibility

The lifecycle follow-up queue can now optionally include outcomes that already have a generated follow-up task. The default remains the actionable queue of outcomes without a task. Set `include_created=true` to review the full outcome-to-task lineage, including task ID, status, assignee, due time, and priority.

This keeps manager oversight in one endpoint while preserving the existing default queue behavior. Tenant and organization-unit scoping continue to apply to both the outcome and linked task.
