# Sprint 205: unified marketing calendar

The CRM exposes one date-range view of planned campaign schedules and CRM work-item due dates. Campaign dates retain channel, objective, and campaign status; work items retain priority, assignment, and status. Each source is scoped independently by its own permission so a user can see the portion of the calendar they are authorized to access.

The range is limited to 93 calendar days. Results are sorted by event date and capped by the requested result limit with a truncation indicator. The view does not trigger campaigns or change work-item state.
