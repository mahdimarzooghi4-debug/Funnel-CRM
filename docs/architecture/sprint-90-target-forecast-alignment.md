# Sprint 90: target-aligned sales forecast

This increment connects approved team/pipeline targets to the existing manager-configured sales forecast.

For every visible target, the alignment report returns:
- Won amount currently recorded in a configured won stage.
- Gross open pipeline and probability-weighted open pipeline for the target period.
- Expected period amount, target gap, and target/forecast attainment percentages.
- Data-quality counts for open opportunities without an amount/currency or configured stage probability.
- A qualitative outlook: target achieved, forecast covers target, forecast below target, or forecast incomplete.

All comparisons remain within one currency. The forecast adds won amount to the weighted open pipeline and uses probabilities configured on pipeline stages. It is a planning estimate, not revenue recognition or a guarantee. The report is read-only and does not modify stage probabilities or opportunities.

Endpoint:
- `GET /api/v1/crm/sales-targets/forecast-alignment` with optional organization and period filters.

Validation includes an integration test for won plus weighted pipeline math and confirms that a high-value opportunity in another currency does not inflate a target.
