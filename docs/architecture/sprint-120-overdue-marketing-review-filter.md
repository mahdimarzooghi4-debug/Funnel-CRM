# Sprint 120: filter the marketing review portfolio to overdue work

The marketing learning portfolio accepts an `overdue_only` filter and the manager workspace exposes it as a checkbox. The API returns only reviews with linked work items that have a due time before report generation and remain open or in progress. Summary counts and pagination are computed for the filtered review set.

The filter requires work-item visibility and is applied within the caller's existing workspace, organization, reporting-period, and permission scopes. It is audited with the other portfolio query parameters. The manager view falls back to the unfiltered review list when work-item details are not authorized, then disables the overdue filter.

Validation covers filtering an in-progress overdue item, excluding it after completion, rejecting requests without work-item inclusion, and the browser request behavior. The feature is read-only and does not change task state.
