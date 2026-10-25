# Sprint 106 — lifecycle follow-up action queue

## Goal

Give marketing managers one scoped view of callback and no-contact outcomes that still need a next action.

## API

`GET /api/v1/crm/work-items/lifecycle-follow-up-queue`

The response is scoped to one authorized organization and includes the customer, recorded outcome, source work item, channel, recorder, and notes. Managers can filter by outcome code or channel and page through results. Outcomes already converted into a follow-up task are removed from the queue, as are customers who are archived or merged. Viewing the queue is audited.

The endpoint is read-only; it does not create work or contact customers.

## Verification

Integration coverage checks filtering, customer and source task context, and removal of an outcome after a follow-up task is created.
