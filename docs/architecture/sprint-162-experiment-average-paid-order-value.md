# Sprint 162: average paid order value in experiment readouts

Campaign experiments can use currency-scoped `average_paid_order_value` from explicitly campaign-linked paid commerce events. The system groups payment events by `(source_product, order_reference)`, sums partial payments within each order, then averages the resulting order totals. Orders from different source products stay distinct, and currencies are never converted or mixed.

The metric requires campaign and commerce-event permissions. Coverage describes dates and source products with paid events in the selected currency. With no matching paid orders the value is unavailable. The result is descriptive, only includes recorded paid events inside the experiment window, and does not net refunds or establish causal attribution.
