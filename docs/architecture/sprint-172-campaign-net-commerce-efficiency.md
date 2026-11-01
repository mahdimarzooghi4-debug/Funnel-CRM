# Sprint 172: net commerce outcomes in campaign analytics

The campaign commerce-efficiency report now includes net paid amount, net paid amount per distinct paid order, and period net paid-to-spend multiple for each currency.

Net amount is recorded paid less recorded refunds. The per-order value divides that amount by distinct paid order keys. The period multiple divides net amount by recorded spend for that currency; unlike experiment readout's daily-paired ratio, it uses the full report period totals. Currency conversion and causal attribution are not applied.
