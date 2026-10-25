# Sprint 103 — lifecycle follow-up outcomes

## Goal

Let an authorized CRM user record what happened during each lifecycle follow-up attempt, then include those explicit outcomes in the lifecycle readout.

## API and data

- `POST /api/v1/crm/work-items/{item_id}/outcomes` records one outcome for a work item created from lifecycle review.
- `GET /api/v1/crm/work-items/{item_id}/outcomes` lists the recorded attempts.
- Outcome codes: `contact_made`, `no_contact`, `callback_requested`, `not_interested`, `other`.
- Each request supplies a tenant-unique `request_id`; exact retries return the original outcome and conflicting reuse is rejected.
- Outcomes record the channel, optional note, occurrence time, and authenticated recorder. The new table is tenant-isolated with row-level security and retains organization, profile, and work-item scope.
- The lifecycle readout adds counts by outcome code.

## Controls and interpretation

Only lifecycle-review work items can receive these outcomes. Recording requires the dedicated `crm.work_item:record_outcome` permission; listing requires `crm.work_item:view`. Every create and list action is audited. Outcomes describe a user's recorded follow-up attempt; they do not establish customer sentiment, retention, revenue, or causality.

## Verification

Database-backed integration coverage exercises create/list, normalized notes, request idempotency, conflicting replay rejection, and inclusion in the readout.
