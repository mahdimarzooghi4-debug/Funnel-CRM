# 011 — Enforce tenant isolation with transaction-local context and PostgreSQL RLS

- **Status:** Accepted
- **Date:** 2026-10-17
- **Scope:** Tenant-aware database access in the shared CRM platform

## Decision

Every tenant-scoped request must use a database transaction with a verified workspace membership and a transaction-local `app.tenant_id` setting. Tenant-owned tables use PostgreSQL row-level security (RLS) policies for both reads and writes. Policies are enabled and forced so table owners are also subject to RLS. The service runtime role must be a non-owner role without superuser or `BYPASSRLS` privileges.

The workspace identifier supplied by a client is only a selector. The server must derive the authenticated issuer and subject from a trusted authentication layer, verify an active membership for that workspace, and only then expose the tenant session. A request header alone is never proof of access.

## Why

Application query filters can be forgotten. RLS adds a database-enforced tenant boundary beneath application code, including for accidentally unscoped ORM queries. Setting the tenant identifier with transaction-local `set_config(..., true)` ties it to one transaction and lets PostgreSQL clear it on commit or rollback before a pooled connection is reused.

## Consequences

- Tenant-scoped reads and writes require the tenant transaction context.
- Missing context sees no tenant rows and cannot insert tenant rows.
- Cross-tenant rows are hidden and cross-tenant writes are rejected by policy checks.
- CI and production must connect as a non-owner role that cannot bypass RLS.
- Migrations and administrative maintenance use a separate privileged database identity.
- RLS complements application authorization; it does not replace workspace membership checks, role and organization-scope checks, or secure query construction.

## Trust boundary and rollout

This decision defines the database and request-context boundary; it does not implement authentication or token validation. Until a trusted authentication middleware is integrated, the API dependency must reject requests without an already-validated identity in request state. Any future integration must populate that state only after cryptographic token validation. Database credentials for the runtime role must not have permission to assume the migration owner role.
