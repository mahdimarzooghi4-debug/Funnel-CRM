# Sprint 158: returns and refunds in experiment readouts

Daily campaign observations now accept returned-order counts and refunded amounts from the source system. Refund values require an amount and ISO currency together, are kept separate from attributed revenue, and are summarized per currency.

Campaign experiment readouts support returned-order count and refunded amount as primary or guardrail metrics. Refund coverage only includes recorded rows in the selected currency; the existing per-variant coverage and source-label reporting applies. CSV templates and imports carry the new fields through the same validation and idempotent batch path.

The CRM does not automatically subtract refunds from attributed revenue. Daily aggregate totals may cover different orders or attribution windows, so the source system must provide any net-revenue or contribution-margin measure it can support.

This implements the returns/refunds portion of [Offer effectiveness experiments](../business/041-offer-discount-effectiveness-experiments.md) without implying causal impact or deduplicating source totals.
