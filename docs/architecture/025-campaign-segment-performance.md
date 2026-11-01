# Campaign performance by audience segment

`GET /api/v1/crm/campaigns/performance/segments?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` groups campaign results by each campaign's configured audience segment, within the caller's authorized campaign scope.

The grouping basis is explicit: measurements are recorded at campaign level and attributed to the segment selected for that campaign. This report does not claim person-level or exposure-level attribution to individuals within a segment. Counts, coverage, and paired-rate bases are aggregated across campaigns; spend, revenue, and planned budgets remain grouped by currency. The report inherits the 366-day period limit and 500-campaign cap and returns a truncation indicator.
