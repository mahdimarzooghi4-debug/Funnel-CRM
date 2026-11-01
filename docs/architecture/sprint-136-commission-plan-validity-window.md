# Sprint 136: Commission plan validity window

Commission plans can carry optional inclusive UTC calendar dates for when their rule applies. The date window is part of every immutable plan version and the plan audit record. A preview or saved calculation is rejected when its requested range falls outside the configured window; an omitted boundary remains unbounded for compatibility with existing plans.

The manager workspace shows and edits both boundaries. No existing plan is assigned an invented historical date during migration.

Validation covers database constraints, invalid date ordering, version history, rejection outside a plan window, and the workspace fields. PostgreSQL CI runs the migration and integration tests.
