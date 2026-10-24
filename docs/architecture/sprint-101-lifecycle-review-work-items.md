# Sprint 101: create work items from lifecycle review

Adds `POST /api/v1/crm/work-items/from-lifecycle-review`, connecting the read-only lifecycle candidate queue to the existing CRM work-item workflow. A manager explicitly selects 1–50 profile IDs and supplies the inactivity rule, optional stage/kind guards, assignee, due date, priority, title prefix, and notes.

Before creating anything, the endpoint checks profile-view and work-item-create permissions, validates every selected profile and active assignee, confirms the profiles still match the selected lifecycle filters, and recomputes the inactivity rule against current recorded activity. If any selected profile no longer qualifies, the whole request returns a conflict without creating a partial batch.

Each created work item carries the selected rule and activity evidence in its description and audit event. Missing linked activity is described as missing CRM evidence, not proof that no contact occurred. This endpoint creates internal tasks only; it does not contact customers or change lifecycle stages.
