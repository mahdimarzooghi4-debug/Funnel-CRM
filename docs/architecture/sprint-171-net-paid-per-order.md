# Sprint 171: net paid amount per paid order

The experiment readout now exposes a currency-specific net recorded amount per paid order: total paid events minus all refunded events, divided by the number of unique paid order keys in that currency and window.

Partial events are summed, paid orders are deduplicated by (source_product, order_reference), and refunds without a matching payment still reduce the numerator. The metric may be negative and describes recorded amounts, not accounting profit.
