# Sprint 170: net paid-to-spend ratio

Experiment readouts can compare net recorded paid and refund events against recorded campaign spend with net_paid_to_spend.

The metric sums daily commerce net (paid minus refunded) and daily actual spend only on dates where both exist for the selected currency, then divides the paired-period net by paired-period spend. It can be negative, excludes unmatched dates from both sides, and is not accounting profit or causal ROAS. This keeps it distinct from reported attributed-revenue ROAS.
