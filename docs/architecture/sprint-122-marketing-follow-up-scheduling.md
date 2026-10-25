# Sprint 122: manage follow-up assignment and due time

The marketing review portfolio now lets a caller with `crm.work_item:update` change an active linked task's due time and optionally assign it to or unassign it from themselves. These changes can be submitted together with a permitted status transition through the existing CRM work-item PATCH endpoint.

The form preserves an existing assignment to another member unless the manager explicitly changes the self-assignment control. It does not reveal the other member's identity. Due times are submitted as timezone-aware instants; blanking an existing due time clears it. The report reloads after a successful update.

Validation covers combined status and scheduling changes, self-assignment, and preservation of another member's assignment. Local browser client, syntax compilation, and diff checks pass. Existing endpoint permission checks and audit events remain authoritative.
