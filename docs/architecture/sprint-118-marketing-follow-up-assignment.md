# Sprint 118: assign and schedule marketing follow-up

Workspace discovery now returns the authenticated user's active membership ID for each workspace, alongside the existing workspace label and root unit. The variance-review workflow can use that scoped identity to optionally assign a generated follow-up task to the current user and record an optional due date. Tasks remain unassigned by default unless the manager checks the explicit self-assignment control.

The existing work-item creation endpoint validates the active membership and `crm.work_item:create` permission. The manager workspace refreshes the review portfolio after review/task creation so the newly recorded work appears immediately. No other workspace membership IDs or identity subjects are exposed.

Validation: browser test covers self-assignment and timezone-aware due date payload; workspace API integration expectations cover the additive membership ID; Python syntax compilation and `git diff --check` pass locally.
