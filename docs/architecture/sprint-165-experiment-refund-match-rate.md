# Sprint 165: matched refund-order rate

Campaign experiments can report `matched_refund_order_rate_percent`: the share of unique refunded orders that also have a paid event for the same `(source_product, order_reference)` within the same campaign and experiment window.

The denominator is all observed unique refunded orders in that window; the numerator is the subset with a matching paid event. The metric has no currency dimension because it measures order linkage, not money. It is unavailable when no refund order is recorded. Its coverage describes refunded-event dates. This is a window-scoped linkage indicator: a payment before the experiment window or without an explicit campaign link is counted as unmatched, so the rate does not establish completeness of the source system's full order history.
