# Campaign measurement quality portfolio

`GET /api/v1/crm/campaigns/performance/data-quality?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` reports data coverage and freshness for campaigns visible to the caller's `crm.campaign:view` scope. The inclusive reporting period is limited to 366 days, with the same 500-campaign cap used by other campaign portfolio reports.

For campaigns with both schedule dates, expected days are the calendar-day overlap between the selected period and the campaign schedule. If the schedule is incomplete, the selected period is used and the response labels that basis. Each metric shows observed, missing, and expected days; a missing value is not treated as zero. The report also counts days with any measurement, days without measurement, measurements outside a complete campaign schedule, source labels, last measured date, and age relative to period end.

Portfolio totals use campaign-days as their unit, so overlapping campaigns contribute separate expected days. This report describes the state of recorded data; it does not infer why a gap occurred or whether a campaign should be paused. Reads are audited with aggregate coverage counts and the period.
