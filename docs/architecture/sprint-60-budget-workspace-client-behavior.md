# Sprint 60: budget comparison client behavior

Adds a dependency-free Node test that executes the actual browser client script with a minimal DOM and mocked same-origin API responses.

It covers automatic identity-scoped workspace and organization loading, the draft scenario request headers and filters, selection of two scenarios, date forwarding to the comparison API, rendered success state, and safe handling of hostile scenario names through text-only DOM content.

GitHub Actions runs this behavior test alongside the PostgreSQL-backed Python suite.

## Validation

Exact head `fa80b42131e9640170fdf33bf0d8427dcbfb8995`: GitHub Actions run `39952774105` succeeded; Alembic passed, pytest reported 94 passed with 3 warnings, and the Node browser-client behavior test passed.
