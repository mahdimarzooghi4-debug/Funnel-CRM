# Sprint 168: matched paid and refund order count

The experiment readout now exposes matched_paid_refund_order_count: distinct (source_product, order_reference) keys with both a paid and refunded event in the same explicitly linked campaign and experiment window.

This count complements the two directional match rates and unmatched counts. It is a descriptive window-level count, requires commerce-event permission, and does not prove that the source contains every payment or later refund.
