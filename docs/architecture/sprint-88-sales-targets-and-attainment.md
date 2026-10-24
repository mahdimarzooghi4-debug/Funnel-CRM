# Sprint 88: sales targets and attainment

This increment lets marketing and sales managers set an amount target for an organization unit, opportunity pipeline, date period, and ISO-style three-letter currency. Targets are tenant scoped and have separate view/manage CRM permissions.

The performance endpoint compares each target against opportunities that currently occupy a configured won stage and whose expected close date is inside the target period. It reports actual amount, won opportunity count, and attainment percentage separately per currency. It does not combine currencies.

**Reporting limitation:** this first version uses the current opportunity stage and expected close date; it does not claim audited cash collection or historical close events. Reopened opportunities therefore follow their current stage.

Endpoints:
- `POST /api/v1/crm/sales-targets` create a target.
- `GET /api/v1/crm/sales-targets` list targets visible to the caller.
- `GET /api/v1/crm/sales-targets/performance` calculate attainment for visible targets.
