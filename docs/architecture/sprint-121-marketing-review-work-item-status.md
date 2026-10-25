# Sprint 121: update linked work status from marketing review

The marketing learning portfolio now offers an explicit status action for linked open work items when the caller has `crm.work_item:update` permission in the selected organization unit. Open items can move to in-progress or completed; in-progress items can be completed. The update uses the existing work-item PATCH endpoint, which retains its tenant checks, transition rules, and audit event.

The report exposes the update capability only for a selected organization unit after checking the existing permission. Users without the grant continue to see the portfolio without status controls. After a successful change, the portfolio reloads so the status and overdue counts reflect the saved record.

Validation covers the manager workspace PATCH request, permission capability response, syntax compilation, and client behavior. Database-backed authorization and transition tests run in CI. No work item is changed without an explicit user action.
