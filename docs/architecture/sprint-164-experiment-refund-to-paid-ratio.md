# Sprint 164: matched-order refund-to-paid amount ratio

Campaign experiments can use currency-scoped `refund_to_paid_amount_percent`. The calculation sums paid events and refund events separately within each `(source_product, order_reference)` and includes only orders with both event kinds in the experiment window. It divides the refund total by the paid total for those matched orders and multiplies by 100.

Events in different currencies are never combined. If there are no matched orders or their paid total is zero, the metric is unavailable. Coverage uses dates with either paid or refunded evidence from the matched orders. This is a descriptive ratio of recorded events, not net revenue, final loss, or causal effect.
