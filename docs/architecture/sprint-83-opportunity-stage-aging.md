# Sprint 83: opportunity stage aging

Expose a tenant- and organization-scoped sales worklist that reports how long currently open opportunities have remained in their current stage, using the stage-entry event from the append-only CRM audit history. The report includes per-stage counts, median and maximum observed days, a configurable minimum-age filter, and stable pagination.

When the audit trail has no matching stage-entry event, duration and stage-entry time remain unknown and the item is marked as incomplete history. Durations are descriptive, based on the caller's reference date, and do not estimate conversion likelihood or imply that an opportunity is stalled.
