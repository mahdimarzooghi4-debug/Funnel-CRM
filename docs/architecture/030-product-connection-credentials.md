# Tenant-managed product connection credentials

- Sprint: 23
- Related: CRM-FND-07
- Management API: `/api/v1/integrations/connections`
- Event API: `POST /api/v1/integrations/events`

A workspace member with `crm.integration:manage` at the workspace root can create, list, and revoke product connections. Each connection is bound to one source product and explicit event-type and contract-version grants. The credential is returned once at creation; the database stores only a SHA-256 digest of a cryptographically random secret. Listing never returns credentials. Revocation takes effect on the next event request.

Product events authenticate with `Authorization: Bearer fc1_<credential-id>.<secret>`. The event envelope's tenant ID is used only as an RLS-protected lookup selector. The key must match a non-revoked connection inside that tenant before the server creates a `VerifiedProductConnection`; event body fields and client headers do not grant access by themselves. Invalid credentials receive the same 401 response.

Creation and revocation write actor-attributed audit metadata with grant counts and credential ID, never the raw credential or secret digest. Product connection records and event inbox rows remain tenant isolated. A product with a credential still receives only its configured source, event, and contract scope.

This sprint does not add credential rotation, IP allowlists, request quotas, inbound replay windows beyond event ID idempotency, or product-specific business handlers. A customer can revoke and recreate a connection to replace a credential until a dedicated rotation workflow is introduced.

Migration: `20261018_12`.
