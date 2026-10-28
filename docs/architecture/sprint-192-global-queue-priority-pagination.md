# Sprint 192: global queue priority and pagination

The campaign decision queue now evaluates and ranks every target plan matching the requested date and organizational scope before applying `offset` and `limit`. This prevents high-attention plans from being skipped because an earlier unranked database page contained lower-priority plans.

The returned page length and `has_more` value are calculated from the ranked result set. Candidate scope remains bounded by the selected date range (maximum 366 days) and the caller's authorized organization units.
