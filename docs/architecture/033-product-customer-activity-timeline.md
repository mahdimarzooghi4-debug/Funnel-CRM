# Product customer activity timeline

- Sprint: 26
- Related: CRM-DOM-02, CRM-DOM-06, CRM-DOM-14
- Contract: `customer.activity.recorded`, `crm.customer.activity` v1

A connected product can append a structured activity to the CRM timeline for a customer already mapped by `customer.upserted`. The mapping is scoped to the authenticated tenant and source product. An activity arriving before its customer mapping remains retryable; it cannot create a profile by itself.

The payload contains only:
- `external_customer_id`
- a stable `activity_type` key
- one of the bounded channels `online`, `phone`, `store`, `field`, `support`, `campaign`, or `other`
- optional source record ID

The envelope's timezone-aware `occurred_at` is retained. No free-text notes, contact values, consent assertion, or campaign-send authorization are accepted. Recording an activity never sends a communication or grants permission to do so.

Activity rows are tenant-isolated, bound to a same-tenant CRM profile, unique by source event, and append-only at the database layer. Profile access follows the existing CRM authorization and organization-scope controls; this integration does not create a new cross-tenant read path. Audit entries contain activity type/channel and source identifiers only.

PostgreSQL tests cover mapping, idempotent event processing, tenant isolation, append-only enforcement, and the separation from communication consent.
