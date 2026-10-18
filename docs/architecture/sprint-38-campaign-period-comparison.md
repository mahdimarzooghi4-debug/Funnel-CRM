# Sprint 38: campaign period comparison

## Purpose

Compare two explicitly selected campaign reporting periods in one request. The periods must have the same number of calendar days and must not overlap. Each period remains limited to 366 inclusive days.

## Results

The comparison returns portfolio totals and channel- or objective-level groups. It includes each side's observed counts, coverage, rates, currency totals, and Sprint 37 efficiency metrics, plus absolute and relative changes where a like-for-like comparison exists.

A metric is comparable only when it has a reported value in both periods. Missing values are not treated as zero. Currency amounts and efficiency ratios are compared only within the same currency. Relative change is null when the comparison-period value is zero.

Groups present in one period remain visible; their one-sided metrics are marked non-comparable. All data remains subject to the existing tenant and organization permissions.
