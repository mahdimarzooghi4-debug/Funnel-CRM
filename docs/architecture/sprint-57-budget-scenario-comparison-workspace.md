# Sprint 57: budget scenario comparison workspace

Adds a Persian right-to-left browser workspace at /workspace/budget-scenario-comparison.

- The page lists draft budget scenarios returned by the existing tenant- and permission-scoped API and loads the read-only comparison endpoint for 2–5 selected scenarios.
- Workspace and organization IDs may be provided as query parameters or entered in the page. They select request scope; authorization still comes from the verified user session, active workspace membership, and CRM view permissions.
- The report shows currency-separated budget reconciliation, recorded campaign spend, leads, conversions, and their recorded-day coverage.
- The interface explains that campaign outcomes are observations and does not attribute them to scenario budgets or convert currencies.
- No new identity provider, business data store, external JavaScript library, or write action is introduced.
- The page and script use same-origin requests, text-only rendering for API data, no-store caching, and restrictive content-security headers.
