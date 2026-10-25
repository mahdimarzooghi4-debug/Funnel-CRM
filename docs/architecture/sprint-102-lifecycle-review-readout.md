# Sprint 102 — lifecycle review follow-up readout

## Goal

Give marketing managers a concise readout of work items created from the customer lifecycle review: item status totals and CRM activities recorded after those items were created.

## API

`GET /api/v1/crm/work-items/lifecycle-review-readout?organization_unit_id={id}`

The endpoint is tenant- and organization-scoped, requires `crm.work_item:view`, and audits each read. It returns review-created work item counts by status plus counts of later recorded activities and distinct profiles with those activities. Work items are identified from their existing `crm_work_item.created_from_lifecycle_review` audit event; no schema migration or second source of truth is introduced.

## Interpretation boundary

The readout reports descriptive timing only. A later activity may have another cause and is not evidence that a follow-up task caused engagement, retention, or revenue. It does not infer churn, sentiment, or causal effectiveness.

## Verification

Integration coverage creates lifecycle review work items, records a subsequent customer activity, and verifies scoped status/activity totals and the interpretation boundary.
