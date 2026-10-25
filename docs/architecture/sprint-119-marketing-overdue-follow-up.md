# Sprint 119: surface overdue marketing follow-up

The marketing learning portfolio now reports how many linked follow-up work items are overdue. A work item counts as overdue when it has a due time earlier than report generation and remains open or in progress. The manager workspace shows this alongside open and completed task totals.

This is a time-based portfolio signal only. It does not change task status, reassign work, or infer why a deadline was missed. The calculation remains scoped to the reviews and work items visible under the caller's existing CRM permissions and selected report filters.

Validation covers an in-progress task with a past due time and its removal from the overdue count after completion, plus manager workspace rendering. Local syntax and client tests pass; the database integration test runs in CI.
