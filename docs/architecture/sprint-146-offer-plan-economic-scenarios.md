# Sprint 146: Offer plan economic scenarios

Marketing offer scenarios let a manager compare assumption-based estimates while an offer plan remains a draft. They are immutable snapshots tied to the plan version at creation. The workflow follows [Sales offer and discount planning](../business/040-sales-offer-and-discount-planning.md).

## API and authorization

- `POST /api/v1/crm/offer-plans/{plan_id}/scenarios` creates a scenario; requires `crm.offer_plan:scenario`.
- `GET /api/v1/crm/offer-plans/{plan_id}/scenarios` lists snapshots; requires `crm.offer_plan:view`.
- Scenarios can only be added while the plan is a draft. An optional catalog price requires `crm.catalog:view`, a linked active item in the same organization unit, and a price effective on the plan start date.
- Price and campaign budget currencies must match for combined revenue comparison. Currency conversion is never inferred.

## Estimates and limits

Expected uses are audience size multiplied by expected use rate. With a selected reference price, gross reference revenue, planned offer value, and revenue after offer are calculated. Campaign budget is subtracted only when its currency matches the reference price. These are planning estimates based on user-provided assumptions, not forecasts or realized results.

The current catalog has no valid unit-cost source. The API therefore always returns `margin_estimate: null` and an explanatory note. No profit or margin claim is made. Scenarios do not change prices, discounts, plan approval, or any sales channel.
