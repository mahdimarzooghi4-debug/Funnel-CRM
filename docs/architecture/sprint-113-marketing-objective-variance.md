# Sprint 113: Marketing objective variance workspace

Campaign target portfolio reports now include additive variance summaries for impressions, clicks, leads, and conversions, both across the portfolio and by channel/objective group. The manager workspace displays these figures and includes the same coverage details in its CSV export.

Actual-to-target variance is calculated only for campaigns whose metric data covers the entire target period. Partial actuals and targets from incomplete periods remain separate; missing data is never treated as zero. Currency metrics and ratios are excluded from additive aggregation. These are arithmetic differences, not explanations of cause.

If the portfolio exceeds the report's campaign limit, the UI withholds the aggregate view rather than presenting the truncated subset as complete.
