# Sprint 108 — durable outcome-to-task lineage

## Goal

Persist the relationship between a recorded follow-up outcome and the work item created from it.

## Data and API

`crm_work_items.source_outcome_id` is an optional tenant-scoped foreign key to `crm_work_item_outcomes`. A unique tenant/source-outcome constraint permits at most one follow-up task per outcome. The work-item response exposes the source outcome ID. Single and batch creation set it; duplicate checks and the action queue use the persisted relation. Audit events remain available as the change history.

The migration is additive and leaves existing work items valid with a null source outcome.

## Verification

Integration coverage checks lineage returned by single and batch creation and verifies the database rejects a second work item for the same source outcome.
