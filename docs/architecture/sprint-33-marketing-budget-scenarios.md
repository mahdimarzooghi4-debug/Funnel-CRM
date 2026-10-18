# Sprint 33: Marketing budget scenarios

## Purpose

Let marketing managers compare hypothetical allocations across existing draft campaigns. A scenario is a planning aid: creating or changing one never changes a campaign's baseline budget and never approves, activates, or spends money.

## Scope and data model

- Each scenario belongs to one tenant and one organization unit.
- Each scenario has a name and draft or archived status.
- Each allocation points to one draft campaign in the same tenant and organization unit, with one non-negative amount and a three-letter uppercase currency.
- A campaign can appear at most once in a scenario. Database composite foreign keys enforce tenant and organization consistency.
- Amounts remain grouped by currency. The CRM does not convert currencies.

## API

- `POST /crm/budget-scenarios`: create a draft scenario and optional allocations.
- `GET /crm/budget-scenarios`: list visible scenarios with allocation counts.
- `GET /crm/budget-scenarios/{id}`: read allocations and totals by currency.
- `PUT /crm/budget-scenarios/{id}/allocations`: replace all allocations on a draft scenario.
- `GET /crm/budget-scenarios/compare?scenario_ids=...`: compare two to five scenarios.
- `POST /crm/budget-scenarios/{id}/archive`: archive a scenario.

Comparisons require all selected scenarios to share an organization unit and allocate exactly the same campaign set. Campaign data access is also required.

## Permissions and isolation

- `crm.budget_scenario:view` and `crm.budget_scenario:manage` govern scenario actions.
- `crm.campaign:view` is required when campaign details are exposed or used.
- PostgreSQL row-level security isolates scenario and allocation rows by tenant. Composite foreign keys also constrain tenant and organization ownership.

## Out of scope

Approval, activation, spend tracking, currency conversion, forecasting, and campaign delivery are not part of this planning feature.
