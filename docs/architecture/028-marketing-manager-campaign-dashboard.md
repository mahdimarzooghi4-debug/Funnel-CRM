# Marketing manager campaign dashboard

`GET /api/v1/crm/analytics/marketing-manager/campaigns?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` composes the authorized campaign performance, channel, configured audience segment, measurement-quality, and target-attainment reports for the same inclusive reporting period.

The dashboard presents currency-separated budgets, spend, attributed revenue, and same-currency efficiency measures; campaign count totals; channel and segment breakdowns; campaign-day and metric-day coverage; target outcomes and variance; and up to 50 manager signals. Target attainment is included only for plans whose period exactly matches the requested dates, following the underlying target-portfolio contract. Commerce outcomes remain subject to the existing commerce permission rules.

The selected period is limited to 366 days. Campaign reports inherit the 500-campaign cap and provide truncation flags; manager signals are separately capped. The dashboard performs an aggregate audit entry and invokes the component reports, which each retain their own read audit. Figures describe recorded data and do not establish that a campaign caused a sales outcome or that a signal should trigger an automatic action.
