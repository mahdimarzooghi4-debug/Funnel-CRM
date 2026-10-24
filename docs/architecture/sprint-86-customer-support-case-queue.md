# Sprint 86: customer support case queue

Add CRM-native support cases linked to active customer profiles and organization scope. Cases have an accountable assignee, priority, manager-supplied response deadline, lifecycle state, audit events, and a queue that can filter to overdue cases and items assigned to the current member.

The response deadline is recorded input; this sprint does not invent a workspace SLA calendar or calculate an automatic due time. Status changes are validated and resolution timestamps are maintained. Reopening a resolved case clears its current resolved timestamp while the append-only audit history preserves the prior resolution event. Closed cases are terminal.
