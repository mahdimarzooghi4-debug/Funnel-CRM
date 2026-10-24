# Product customer profile synchronization

- Sprint: 25
- Event: `customer.upserted`
- Contract: `crm.customer` version 1

This is the first business-event handler over the durable product inbox. It maps a source product's external customer ID to one CRM profile within the same tenant. Repeated upserts update that profile instead of creating another one. Product customer IDs are scoped by both tenant and source product.

The payload contains an external customer ID, profile kind, display name, and up to 20 contact points. Contact values are encrypted using the CRM contact-point keyring before insertion and indexed with tenant/channel-bound blind indexes. New contact points stay `unverified`. This contract carries no consent fields and creates no communication-consent events.

Profiles are created as leads under the tenant's root organization. If that profile kind has active required custom fields, processing fails with a safe machine error until a mapping is provided; this handler does not bypass tenant configuration. Archived, merged, or type-conflicting linked profiles are not overwritten. Unhandled event types become non-retryable failures in this dedicated customer consumer.

A durable source-to-profile identity mapping makes reprocessing safe if a worker crashes after the CRM transaction and before inbox acknowledgement. Audit records contain only event and profile metadata, never contact values. Consumer processing is tenant-scoped and at-least-once.

Required runtime secrets:
- `FUNNEL_CRM_INTEGRATION_PAYLOAD_KEYRING` for inbox payload decryption
- `FUNNEL_CRM_CONTACT_KEYRING` for CRM contact encryption

Migration: `20261018_15`.
