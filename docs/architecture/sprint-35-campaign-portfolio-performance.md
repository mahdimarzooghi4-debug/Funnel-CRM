# Sprint 35: campaign portfolio performance

## Purpose

Compare recorded campaign results across a selected date range. The portfolio report includes campaigns with measurements in that range, groups them by channel or objective, and returns a sortable, paginated campaign list.

## Report contents

- Observed metric totals and campaign-day coverage for impressions, reach, clicks, responses, leads, and conversions.
- Click-through, lead-per-click, and conversion-per-click rates calculated only over campaign-days where each numerator and denominator were both reported.
- Planned campaign budgets, actual spend, and attributed revenue, each grouped independently by currency. Planned budgets represent the campaign's full plan; actuals reflect only the selected reporting period.
- Campaign status, organization unit, and baseline budget in the campaign rows to preserve context.

Groups and portfolio totals are computed over the full matching set, independent of the campaign-list page. An unmeasured campaign is not presented as a measured result. No currencies are converted or combined.

## Access and limits

The report requires `crm.campaign:view` and respects the caller's tenant and inherited organization scope. Reporting is limited to 366 inclusive calendar days. Campaign rows are ordered by the chosen observed count (conversions, leads, or clicks), with stable name and ID tie-breaks; pagination does not change totals.
