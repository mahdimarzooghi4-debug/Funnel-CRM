# Campaign performance by channel

`GET /api/v1/crm/campaigns/performance/channels?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` groups the existing campaign performance portfolio by channel for the authorized campaign scope and selected inclusive period.

For each channel it reports campaign and measured-campaign counts, per-metric observed coverage, count totals, spend and attributed revenue by currency, and planned budget by currency. Rates are recomputed from paired numerator and denominator observations across all campaigns in the channel; they are not averaged from per-campaign percentages. The response is capped by the same 500-campaign portfolio limit and exposes truncation.

This is a descriptive comparison. Currency groups are not converted, and no campaign ranking or automated recommendation is applied.
