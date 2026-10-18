# Sprint 37: campaign efficiency metrics

## Purpose

Extend campaign portfolio reporting with decision-ready unit economics: cost per lead, cost per conversion, and return on ad spend (ROAS). Results appear at campaign, channel/objective group, and portfolio levels.

## Pairing and currency rules

- Cost per lead and cost per conversion include only campaign-days where actual spend and the matching outcome count were both reported.
- ROAS includes only campaign-days where actual spend and attributed revenue were both reported in the same currency.
- Portfolio and group calculations add paired spend and outcomes before dividing; they do not average campaign ratios.
- Each result includes paired campaign-day coverage and its underlying sums. A zero outcome or zero spend leaves the ratio null.
- Currency amounts are never converted or combined. A different-currency revenue observation remains visible in the existing revenue totals but is excluded from ROAS.
- Ratios are rounded to six decimal places.

## Boundaries

Metrics describe the entered reporting data and its source labels. They do not establish attribution quality, forecast future results, recommend spend, or approve campaign budgets. Existing tenant and organization scopes apply.
