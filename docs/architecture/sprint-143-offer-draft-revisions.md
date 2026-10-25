# Sprint 143 — Offer draft revision history

Adds immutable, linked revisions to opportunity offer drafts. A revision preserves its own catalog and price snapshots, records its revision number and predecessor, and can only be created from the latest revision in that opportunity. The offer workspace shows revision history and lets a user prepare an edited successor from the latest draft.

The API revalidates current item scope, attachment, active state, catalog version, selected effective price, currency, and quantity for each revision. Superseded revisions remain readable and unchanged. Revision creation uses the existing offer-create and catalog-view permissions and writes a distinct audit event. No offer is sent or accepted, and this does not create an order or contract.

Validation covers route registration, immutable predecessor snapshots, sequential revision metadata, stale-branch rejection, frontend rendering, and the full PostgreSQL CI suite.
