# Sprint 59: budget comparison user journey

Connects the identity-based selectors from Sprint 58 to the existing read-only scenario comparison workflow.

The integration test exercises the journey through the HTTP application: authenticated identity → active workspace choices → permission-filtered organization units → scenario creation and listing → observed-performance comparison. The browser-client contract test checks that the page calls the same selection and comparison endpoints.

The journey remains read-only with respect to campaign execution and makes no budget recommendation. It reports recorded evidence only.

## Validation

Pending exact-head CI.