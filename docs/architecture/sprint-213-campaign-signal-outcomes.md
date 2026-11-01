# Sprint 213: Campaign signal follow-up outcomes

Managers can record a structured outcome on campaign-signal work items: adjusted, data corrected, no change, escalated, or other. The API snapshots the current metric value, status, and measurement coverage at the time of the recorded decision. These snapshots provide history for later review; they do not claim the work item caused a change in campaign performance.

Outcome writes are tenant-scoped, permission checked, idempotent by request ID, and audit logged. A dedicated table keeps the campaign-signal outcome path separate from customer-contact outcomes that require a customer profile.
