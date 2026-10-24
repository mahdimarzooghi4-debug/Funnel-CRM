# Sprint 98: track corrective-action execution in the learning portfolio

The marketing learning portfolio can optionally include its linked CRM work items. With `include_work_items=true`, the response shows each corrective action's current assignee, due date, priority, and lifecycle status, plus scope- and filter-matched counts for linked, unlinked, open, in-progress, completed, and cancelled actions.

The optional data requires both campaign-view and work-item-view permissions. Explicit organization requests are checked against the relevant permissions. Existing portfolio responses stay free of work-item data unless requested. Task status remains manager-controlled through the existing CRM work-item update endpoint; no action is auto-completed.

Integration coverage moves a linked corrective action through in-progress and completed states and verifies the portfolio reflects those transitions and counts.
