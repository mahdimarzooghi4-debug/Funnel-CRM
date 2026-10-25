# Sprint 129: Export the complete filtered learning portfolio

The marketing learning portfolio can export every matching review across API pages, using the currently selected campaign, lesson, status, and overdue filters. The CSV includes review context, baseline and follow-up periods, recorded assessment and action, learning fields, and linked CRM work-item status and due date when available.

Export requests use the active workspace and organization scope and follow the API's bounded page size. Formula-like text is escaped by the existing CSV cell encoder. Exports stop at 100,000 rows and tell the user to narrow filters above that limit.

Validation: browser-client behavior test, Python compile check, and `git diff --check`.
