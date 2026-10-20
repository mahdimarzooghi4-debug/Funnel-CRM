# Sprint 52: Marketing metric catalog

The read-only `GET /api/v1/crm/analytics/metrics` endpoint exposes a versioned glossary for the campaign analytics already implemented in Funnel CRM.

## Scope and behavior

- Every request names an `organization_unit_id` and requires `crm.campaign:view` in that scope.
- Commerce definitions are returned only when the viewer also has `crm.commerce_event:view`.
- Optional `category` and `search` filters support browsing the catalog.
- Each definition identifies its formula, source fields, aggregation rule, dimensions, unit, currency handling, missing-data behavior, limitations, endpoint, and required permissions.
- Catalog reads are audited. The catalog describes current reporting behavior; it does not create new calculations.

## Metric interpretation

Campaign activity and funnel rates come from daily campaign measurements. Rates use totals from days where both numerator and denominator are recorded. Spend and reported attributed revenue are grouped by currency, without foreign-exchange conversion. The existing reported ROAS uses same-currency daily measurement values and is distinct from paid-to-spend based on explicitly campaign-linked commerce events. Commerce definitions do not claim causal attribution; refunds remain separate from paid amount. Recorded-day coverage describes data presence and does not treat missing days as zero activity.
