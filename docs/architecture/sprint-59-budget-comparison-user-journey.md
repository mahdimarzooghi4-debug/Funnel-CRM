# Sprint 59: budget comparison user journey

Connects the identity-based selectors from Sprint 58 to the existing read-only scenario comparison workflow.

The integration test exercises the journey through the HTTP application: authenticated identity → active workspace choices → permission-filtered organization units → scenario creation and listing → observed-performance comparison. The browser-client contract test checks that the page calls the same selection and comparison endpoints.

The journey remains read-only with respect to campaign execution and makes no budget recommendation. It reports recorded evidence only.

## Validation

- Exact implementation head `d240b8f57d715fd811f70179604f0e2ad47ee9a6`: GitHub Actions run `39637177209` succeeded; Alembic upgrade passed and pytest reported 94 passed, 3 warnings.
- The initial run found a same-name CTE collision in the combined permission query; the implementation was corrected and the full suite passed.