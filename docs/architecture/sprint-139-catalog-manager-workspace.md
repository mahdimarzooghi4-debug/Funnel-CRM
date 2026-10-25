# Sprint 139 — Catalog manager workspace

## Scope

Adds a Persian, right-to-left manager workspace at `/workspace/crm-catalog` for the product and service catalog introduced in Sprint 138. It supports organization-scoped item creation, version-aware item updates and deactivation, and append-only price versions with history.

The workspace obtains permitted workspaces and catalog organization units from the existing system APIs, sends the selected workspace in `X-Workspace-ID`, and relies on catalog API permissions for every read and write. UI output is inserted as text nodes; no catalog content is interpreted as HTML. The page is non-cacheable and uses a restrictive same-origin CSP.

## Validation

- Application route and security-header tests
- Script route and safe DOM handling assertions
- Existing catalog API integration tests (requires `TEST_DATABASE_URL`)
