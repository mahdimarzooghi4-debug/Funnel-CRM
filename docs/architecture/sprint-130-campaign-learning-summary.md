# Sprint 130: Campaign-level marketing learning summary

The marketing learning portfolio reports, for each campaign in the active scope and filters, the number of reviews and how many are planned or evaluated. Aggregates are computed over the full filtered result set, independent of the current page, and follow the same tenant, organization, period, lesson, campaign, status, and overdue filters.

The interface labels this as a review/workflow summary; it does not imply campaign effectiveness or causal impact. The API aggregate contains only authorized campaign review records.

Validation: browser-client behavior test, API module import, Python compile check, and `git diff --check`. Database integration tests require `TEST_DATABASE_URL` and run in CI.
