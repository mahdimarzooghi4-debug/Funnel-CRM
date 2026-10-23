# Sprint 69: recorded cost per result

Add a channel-level descriptive ratio for recorded spend per recorded lead and per recorded conversion, compared between equal-length reporting periods. Calculate only from campaigns with both spend and the selected metric recorded, and only when each campaign has exactly one recorded spend currency. Keep currencies separate.

Exclude ambiguous multi-currency campaigns rather than allocating results across currencies. A zero result denominator, missing observations, or negative aggregate spend produces an unavailable unit cost. This ratio is not ROI, revenue, or causal evidence about a budget scenario. Include the current value and comparison context in CSV exports.

## Validation

Pending exact-head CI.
