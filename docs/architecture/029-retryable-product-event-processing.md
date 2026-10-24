# Retryable product event processing

- Sprint: 22
- Related: CRM-FND-07
- Inbox table: `integration_event_inbox`

This sprint adds a tenant-scoped processing lifecycle for events already durably accepted by Sprint 21. Internal workers claim bounded batches under PostgreSQL row locks with `SKIP LOCKED`; each claim receives a fresh lease token and expiry. A crashed worker's lease can expire and another worker can reclaim the event. An old worker cannot complete or fail an event after its lease has been replaced.

Successful work marks the inbox row `processed`. Failures accept only a short machine-readable error code; raw exception text and payload data are not stored as failure metadata. Retryable failures return to `received` with capped exponential backoff. Non-retryable failures and exhausted attempts become `failed`. The attempt limit and lease/backoff bounds are configurable when constructing the internal processor.

The API still acknowledges only durable receipt. No public worker endpoint, credential issuance, product-specific business handler, campaign delivery, or exactly-once external side effect is introduced. Delivery is at-least-once, so consumers must make external effects idempotent using the event ID. The processor requires an explicit tenant ID and applies the existing tenant RLS context for every operation.

Migration: `20261018_11`.
