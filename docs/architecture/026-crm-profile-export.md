# Scoped CRM profile CSV export

- Sprint: 19
- Related: CRM-DOM-02
- API: `GET /api/v1/crm/profiles/export.csv`

Exports require both `crm.profile:view` and `crm.profile:export` in the same applicable organization scope. The query enforces both scopes in SQL and excludes archived and merged profiles. An optional organization filter narrows the result.

CSV contains profile ID, organization, kind, display name, lifecycle stage, and creation/update timestamps. It excludes encrypted contact points, consent records, and custom field values. The endpoint caps each request at 10,000 rows, supports offset batches, refuses oversized unbatched exports, neutralizes spreadsheet formula prefixes, sends no-store headers, and writes an actor-attributed audit event with row/batch metadata but no profile values.

PostgreSQL/API tests cover scoped authorization, the CSV response shape, formula safety, and export audit history.
