# Controlled merging of duplicate CRM profiles

- Sprint: 17
- Related: CRM-DOM-02
- API: `POST /api/v1/crm/profiles/{profile_id}/merge-into/{target_id}`

A user must have profile view, profile update, and duplicate review permissions in the organization scope of both records. The operation locks both rows, requires the same Workspace and profile kind, rejects self-merges and already-merged targets, and is idempotent when the source already points to the same survivor.

The source remains stored with its original identity and history. The database records a same-tenant pointer to the surviving profile and emits an append-only actor-attributed audit event. Normal profile lists omit merged sources; reading a source shows the surviving profile ID. Related records remain attached to the source so encrypted contact values and append-only communication decisions are not rewritten or lost. Duplicate suggestions omit merged records.

This operation records a human-reviewed relationship; it does not guess which field values, encrypted contact points, or communication decisions should overwrite another record. Those histories remain accessible through the original profile while downstream views can resolve the survivor pointer.

PostgreSQL/API tests cover permissions, same-kind enforcement, idempotency, self-merge rejection, list behavior, source preservation, and audit attribution.
