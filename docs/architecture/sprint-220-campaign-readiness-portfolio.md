# Sprint 220: Campaign readiness portfolio

## Goal

Give campaign managers one paginated view of draft campaigns that need review, rather than requiring them to open each campaign separately.

## API

`GET /api/v1/crm/campaigns/readiness-portfolio`

Optional query parameters:

- `organization_unit_id`: limit the view to an authorized organization scope.
- `limit`: page size from 1 to 100 (default 50).
- `offset`: zero-based page offset.

The response includes the total number of draft campaigns in the authorized scope, page metadata, ready-for-manager-review and needs-attention counts for the current page, counts of incomplete checks on the page, and each campaign's full readiness checklist.

## Access and behavior

- Campaigns are limited to the tenant and campaign-view organization scopes.
- Requesting an organization outside those scopes returns 403.
- Detailed checks reuse the single-campaign readiness rules, including consent and verified-contact eligibility.
- The summary is read-only and never sends or launches a campaign.
- The endpoint records an audit event for the review.
- Counts such as readiness and attention-by-check describe the returned page; `total_draft_campaigns` describes the entire authorized filtered result.

## Verification

The campaign lifecycle API test checks portfolio pagination metadata, page-level counts, the campaign entry, and attention counts while the campaign still lacks channel consent eligibility.
