# Campaign budget consumption

The campaign performance portfolio includes a `budget_consumption` object per campaign. It compares measured spend within the requested reporting period with the campaign's planned budget, using only spend recorded in the budget currency.

`measured_spend_in_budget_currency`, `remaining_amount`, and `consumed_percent` are null if the campaign has no planned budget currency or no measured spend in that currency. An observed zero remains zero. The remaining amount may be negative when measured spend exceeds plan. Percentage is null if the budget is zero. Spend recorded in other currencies is returned separately and is never converted or included in the comparison.

This view reports period spend against the stored campaign budget; it does not forecast end-of-campaign spend or recommend budget changes.
