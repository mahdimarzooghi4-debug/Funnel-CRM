# Sprint 82: opportunity stage history

Expose a read-only, tenant- and organization-authorized timeline from the existing append-only audit events for a sales opportunity. The history reports create/update events, timestamp, actor identity reference, stage transition, and changed CRM fields with pagination. Viewing history is audited separately and does not appear as an opportunity edit.

This is an audit-backed record of changes. It does not infer time-in-stage, probability, or sales outcomes.
