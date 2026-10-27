# Sprint 166: unmatched paid and refund orders

Campaign experiment readouts can report two complementary counts using unique `(source_product, order_reference)` keys within each explicit campaign and experiment window:

- `unmatched_refund_order_count`: refunded orders without a matching paid event in that same window.
- `paid_order_without_refund_count`: paid orders without a matching refund event in that same window.

Both require campaign and commerce-event permissions and have no currency dimension. Their coverage is based on the relevant unmatched event dates. No recorded refund means only that no refund event was observed in this window; it does not establish that no later refund occurred. Payments outside the period or lacking explicit campaign linkage are unmatched for this readout, which does not establish completeness of a source system's full order history.
