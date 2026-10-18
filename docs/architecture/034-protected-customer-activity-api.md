# Protected customer activity timeline API

- Sprint: 27
- Related: CRM-DOM-02, CRM-DOM-14
- Route: `GET /api/v1/crm/profiles/{profile_id}/activities`

The CRM timeline read endpoint returns paginated structured activity records for one profile. It requires the caller's existing `crm.profile:view` permission, and applies the effective organization-unit scope in SQL before counting or returning rows. A profile outside the tenant or caller scope returns 404.

The response contains only activity ID, source product, type, channel, optional source record ID, occurrence time, and ingestion time. It never returns the original event payload. Reads create a user-attributed audit entry with pagination and result counts, without activity content.

The PostgreSQL/API test exercises an authorized read, cross-tenant 404 behavior, timestamp and field shape, and the metadata-only audit record.
