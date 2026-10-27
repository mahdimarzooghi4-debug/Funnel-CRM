# Sprint 179: decision queue commerce summary

The campaign decision queue now includes linked paid, refunded, and net amounts grouped by currency for campaigns where the viewer has commerce-event access. This gives managers a compact commercial outcome beside each campaign's target and coverage status.

The amounts remain observational. The queue does not infer product-specific spend allocation, causal advertising return, or automatic action. Campaigns without commerce permission return no commerce outcomes.

Validation: the decision-workspace regression test verifies USD paid/refund/net amounts and an independent EUR net amount in the queue.
