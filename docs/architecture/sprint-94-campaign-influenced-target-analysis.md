# Sprint 94: campaign influence against sales targets

This read-only analysis joins CRM campaign-tagged customer activity to opportunities in a target's pipeline and expected-close period. It shows campaign-level associated opportunity counts, profiles, prior touch counts, won/lost amount, and probability-weighted open pipeline.

Association rule: a customer activity is linked only when the same profile, tenant, and organization has a campaign-tagged activity at or before opportunity creation. The target report also requires the opportunity expected close date to be within the target period. One opportunity may be associated with multiple campaigns.

Campaign-level values can therefore overlap. The response also returns unique opportunity-level totals and the count of multi-campaign opportunities. It explicitly marks causal attribution and currency conversion as not applied. The report is an observed association, not evidence that a campaign caused the opportunity or revenue.

The endpoint requires target-view, campaign-view, and opportunity-view permissions in the target organization scope and records report access in the audit log.

Endpoint:
- `GET /api/v1/crm/sales-targets/campaign-influence?target_id=...`

Integration coverage verifies multi-touch overlap, deduplicated target totals, weighted pipeline math, and currency isolation.
