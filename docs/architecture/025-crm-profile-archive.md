# CRM profile archive and restore

- Sprint: 18
- Related: CRM-DOM-02
- API: `POST /api/v1/crm/profiles/{profile_id}/archive` and `POST /api/v1/crm/profiles/{profile_id}/restore`

Archiving is a soft lifecycle action. It records an archive timestamp while retaining the stable profile ID, custom field values, encrypted contact points, consent history, and related records. Repeated archive and restore requests are idempotent.

Both actions require the independent `crm.profile:archive` permission in the profile's organization scope. Ordinary profile lists omit archived records. `include_archived=true` returns only archived rows in the caller's view scope that is also covered by archive permission. Direct reads remain available to users with profile view permission. Archived profiles cannot be updated or merged; merged sources cannot be archived or restored.

The database emits append-only, actor-attributed audit events for archive and restore state changes. PostgreSQL/API tests cover list visibility, idempotency, restoration, and audit history.
