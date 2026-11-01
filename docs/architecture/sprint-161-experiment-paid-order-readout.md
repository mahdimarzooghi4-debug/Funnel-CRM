# Sprint 161: paid-order count and amount in experiment readouts

Campaign experiments can use `paid_order_count` and currency-scoped `paid_amount` from paid commerce events explicitly linked to a variant campaign. Paid orders are counted once per `(source_product, order_reference)`; `paid_amount` sums qualifying paid-event amounts in the selected currency and may therefore reflect multiple recorded payment events for an order.

Both metrics require campaign and commerce-event permissions. Coverage lists the dates and source products with matching paid-event evidence; absent event days remain unknown rather than zero. These metrics complement the order-linked refund count and rate, but do not automatically net refunds from paid amount and do not imply causal attribution.
