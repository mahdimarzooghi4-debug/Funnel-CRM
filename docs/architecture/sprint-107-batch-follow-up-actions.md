# Sprint 107 — batch follow-up actions

## Goal

Let a manager turn a selected set of queued outcomes into customer tasks in one operation.

## API

`POST /api/v1/crm/work-items/outcomes/follow-up-batch`

The request scopes a unique selection of up to 100 outcome IDs to one organization and may set one active assignee, timezone-aware due date, and priority for the batch. Every outcome must still be a callback request or no-contact result, have an active customer, and not already have a follow-up task. If any selected record fails validation, the whole request is rejected; it never creates a partial batch. Successful task and source-outcome records are audited.

## Verification

Integration coverage checks all-or-none rejection for an unsupported outcome, successful multi-customer creation, removal of completed selections from the action queue, and replay conflict.
