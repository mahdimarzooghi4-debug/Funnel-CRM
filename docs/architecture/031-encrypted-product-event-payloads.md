# Encrypted product event payloads

- Sprint: 24
- Related: CRM-FND-07
- API: `POST /api/v1/integrations/events`

New inbox events encrypt their JSON payload with AES-256-GCM before persistence. The database stores the encryption key ID and nonce-prefixed ciphertext; the legacy JSONB payload is an empty object for encrypted rows. The event envelope digest is also HMAC-SHA256 with a domain-separated integration key, avoiding a dictionary-guessing side channel. Its key ID is stored for verification across key rotation. Authenticated associated data binds decryption to the tenant, event ID, source product, event type, and contract version, so moving ciphertext between events or tenants fails integrity validation.

Configure `FUNNEL_CRM_INTEGRATION_PAYLOAD_KEYRING` in deployment secret storage as JSON with an `active_key_id` and a `keys` object whose values are base64-encoded 32-byte keys. Keep old key IDs available while events encrypted with them may still be retried. Missing or invalid key configuration fails event ingestion closed with `503`; worker decryption errors do not expose payload data.

Existing inbox rows remain readable through their prior JSONB payload column. New event processing decrypts encrypted rows only after they are claimed. This migration does not rewrite legacy rows.

Migrations: `20261018_13` (payload encryption) and `20261018_14` (keyed event digests).
