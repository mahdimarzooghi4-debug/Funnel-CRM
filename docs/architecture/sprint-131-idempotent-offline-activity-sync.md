# Sprint 131: Idempotent offline activity sync API

The offline client creates a UUID once per activity and preserves it for every retry. The CRM sync endpoint derives the tenant from the authenticated workspace, checks `crm.profile:update` scope, and accepts only the app's own activity source. A repeated event ID with the same normalized fields returns the stored activity as a duplicate receipt; reuse with different fields returns `409` for user review. PostgreSQL's existing tenant policy and unique key remain the final isolation and duplicate barrier.

The first client contract stores only activity metadata and CRM identifiers, not customer notes or copied profile data. The server records one metadata-only audit event for a newly stored activity; retries do not create duplicate audit entries. Invalid, unauthorized, or conflicting records remain unresolved for the client to show in a later sprint.

Validation: API integration coverage for new sync, same-event retry, conflicting reuse, and single audit entry; module import and compile checks. The integration test requires `TEST_DATABASE_URL` and is run in CI.
