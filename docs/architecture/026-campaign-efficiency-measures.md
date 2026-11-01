# Campaign efficiency measures

Campaign performance, channel performance, segment performance, and period comparison responses include efficiency measures per currency:

- `attributed_revenue_minus_spend_by_currency`: observed attributed revenue minus observed campaign spend in the same currency. This is not accounting profit; it excludes other costs and adjustments.
- `return_on_ad_spend_by_currency`: attributed revenue divided by actual spend in that currency, expressed as a ratio (for example, `5.0` means 5x).

A currency appears only when both revenue and spend are observed for that currency. Revenue minus spend is retained when spend is zero; the ratio is omitted when spend is zero. No exchange rates or currency conversion are applied. Period comparisons carry these measures inside each period's campaign item so values remain tied to the selected reporting window.
