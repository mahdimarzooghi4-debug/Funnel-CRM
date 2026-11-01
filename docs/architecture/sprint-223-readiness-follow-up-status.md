# Sprint 223: Follow-up status in campaign readiness

The campaign readiness response now includes the live status of the follow-up work item linked from the latest manager review, plus its assignee and due date.

Follow-up details, including the work item ID, are returned only when the caller has `crm.work_item:view` access in the campaign's organization scope. Campaign viewers without that permission still see the recorded review decision, but follow-up fields are null.

The values are read from the work queue each time readiness is requested, so completing, cancelling, or reassigning a task is reflected without rewriting the append-only review audit event.
