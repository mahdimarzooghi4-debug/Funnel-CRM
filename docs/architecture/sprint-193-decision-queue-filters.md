# Sprint 193: decision queue filters

The campaign decision queue accepts an optional status filter and an optional attention-reason filter. The filters apply to the fully ranked result set before pagination; `total_count` and `has_more` describe the filtered set.

Only documented queue statuses and attention-reason keys are accepted. Filter values are included in the audited view event.
