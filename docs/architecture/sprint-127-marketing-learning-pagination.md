# Sprint 127: paginate the marketing learning portfolio

The portfolio API now returns its selected `limit` and `offset` with each report. The manager workspace exposes previous and next page controls and shows the visible result range against the filtered total.

Pagination preserves the selected reporting period, overdue filter, and lesson search. Changing the search or overdue filter and loading a new report reset the list to its first page. Existing tenant and organization authorization continues to apply before page selection.

Validation covers API pagination metadata and empty-page behavior, plus browser navigation in both directions while preserving the active lesson query.
