# Sprint 163: average refund per order in experiment readouts

Campaign experiments can use currency-scoped `average_refund_per_order` from explicitly linked refund events. Refund events are grouped by `(source_product, order_reference)`, partial refunds are summed within each order, and the order totals are averaged. Source products and currencies remain separate.

The metric requires campaign and commerce-event permissions. Coverage describes dates and source products with matching refund events. Without recorded refunds in the selected currency, the value is unavailable. It is descriptive, includes only events in the experiment window, and does not infer that no refunds occurred when evidence is missing.
