# Durable product event inbox

- Sprint: 21
- Related: CRM-FND-07
- API: `POST /api/v1/integrations/events`

Product integrations now have a PostgreSQL-backed inbox. The API validates the trusted connection grant, writes the event and its SHA-256 envelope digest under the connection's tenant context, and returns `202 Accepted` only after the transaction commits. If a custom `ProductEventSink` is injected it remains available for controlled adapters and tests; otherwise the route uses the app's `session_factory`. Missing durable storage fails closed with `503`.

The unique key `(tenant_id, source_product, event_id)` makes retries safe. A byte-equivalent normalized envelope returns a duplicate receipt. Reusing an event ID for a different envelope returns `409`. PostgreSQL row-level security scopes inbox rows to the tenant. A database trigger records metadata-only system audit events in the same transaction; payload content is not copied into audit state.

The inbox lifecycle starts at `received`. This sprint does not process business events, deliver campaigns, or claim downstream completion. Credential issuance and validation remain the responsibility of trusted product-connection middleware.

Migration: `20261018_10`.
