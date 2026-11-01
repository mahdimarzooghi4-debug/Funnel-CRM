# Sprint 167: paid-order refund match rate

The experiment readout now exposes paid_order_refund_match_rate_percent: unique paid orders with a matching refund event divided by unique paid orders in the same explicitly linked campaign and experiment window.

Together with matched_refund_order_rate_percent, it shows the two directions of the same overlap: what share of refunds has a matching payment, and what share of payments has a recorded refund. Both are descriptive window-level observations, require commerce-event permission, and have no currency dimension. No recorded refund in the window does not establish that a later refund never occurred.
