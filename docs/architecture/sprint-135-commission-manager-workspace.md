# Sprint 135: Commission manager workspace

The commission manager workspace is a Persian RTL, same-origin page over the existing commission APIs. It lets an authorized manager create organization-wide or seller-specific plans, update a plan by its current version, inspect immutable plan-version history, generate calculation snapshots, and review prior calculations.

Workspace choices come from active identity memberships. Organization choices use a dedicated endpoint scoped by `crm.commission:view`; plan writes and calculations continue to enforce `crm.commission:manage` in the API. The page shell contains no customer or tenant data and uses `no-store` plus restrictive browser headers.

The workspace can preview a calculation without persisting a snapshot. The preview reads current commerce events; creating the snapshot reads them again, so later events can change the saved result. Calculation requests include a UUID retained in session storage until the server confirms success. If the response is lost, retrying the same period replays the stored snapshot. Reusing the request ID for a different period is rejected by the API.

Validation covers page direction and security headers, safe DOM rendering, API paths and workspace headers. PostgreSQL CI verifies organization-scope selection and commission permissions alongside the complete migration and Python suites.
