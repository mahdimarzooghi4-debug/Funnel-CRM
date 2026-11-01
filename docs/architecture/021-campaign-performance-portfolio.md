# Campaign performance portfolio

CRM campaign measurements can be reviewed together through:

`GET /api/v1/crm/campaigns/performance?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD`

The endpoint requires the caller's `crm.campaign:view` organization scope and returns up to 500 campaigns visible in that scope. The requested inclusive period can span at most 366 calendar days. If more than 500 campaigns are visible, `truncated` is true.

Each campaign item includes its planned budget, measurement record count, source labels, observed-day coverage per metric, available count totals, click-through/lead/conversion rates, and actual spend and attributed revenue grouped by currency. Amounts in different currencies are never combined. Rates use only records where both numerator and denominator were observed, and are null when the denominator is zero or no paired data exists. Missing observations remain null, distinct from an observed zero.

The response reports campaign and measured-campaign counts. Reads are audited with the date range, returned campaign count, measured count, and truncation state; no customer-level data is included. The endpoint presents observed evidence and does not apply performance thresholds or make automatic campaign decisions.
