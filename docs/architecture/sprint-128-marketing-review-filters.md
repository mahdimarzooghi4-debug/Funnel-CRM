# Sprint 128: filter marketing reviews by campaign and status

The learning portfolio now combines its lesson search with a campaign-name search and a review-status selector. The API applies each filter before counting and pagination, and returns the normalized campaign query alongside existing report metadata.

Filters continue to use the caller's existing tenant, organization, and campaign-view scopes. Campaign search treats SQL wildcard characters literally. Pagination preserves all active filters.

Validation covers case-insensitive campaign matching, planned/evaluated status filtering, and browser requests that carry filters into later pages.
