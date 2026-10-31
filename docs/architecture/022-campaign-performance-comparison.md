# Campaign performance period comparison

`GET /api/v1/crm/campaigns/performance/compare` accepts:
- `current_start` and `current_end`
- `previous_start` and `previous_end`

Both inclusive date ranges must have the same number of days and each is limited to 366 days. Authorization and campaign cap follow the campaign performance portfolio endpoint.

The response includes each period's original campaign item where that campaign has observations in the period, alongside changes in count metrics, rates, spend, and attributed revenue. A campaign absent from one period is represented as null for that period. Null observations remain distinct from zero. Percentage change is null when either period has no observed value or the previous value is zero. Money comparisons are only made for the same currency; currencies present in only one period have no delta.

Each underlying portfolio read is audited independently with the date range and scope summary. The comparison does not infer causes or assign performance grades.
