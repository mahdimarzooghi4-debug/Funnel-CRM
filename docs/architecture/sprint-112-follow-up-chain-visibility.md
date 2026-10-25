# Sprint 112: Follow-up chain visibility

The lifecycle manager queue now follows one additional step in the outcome-to-task chain. For a generated task with a recorded callback or no-contact outcome, the queue includes the next task created from that latest outcome, with status, assignee, and due time.

This builds on the latest-outcome summary and uses persisted outcome-to-task links. It does not infer relationships from audit text, and tenant and organization-unit scope are applied to the linked task.
