# Sprint 159: order-linked refunds in experiment readouts

Campaign experiments can use `refunded_order_count` and `refund_amount` from source-recorded commerce events. Events must explicitly carry the variant campaign ID, have `event_kind=refunded`, and fall within the experiment window. Metrics are tenant-, organization-, campaign-, and currency-scoped and require `crm.commerce_event:view` in addition to campaign access.

An order is identified by `(source_product, order_reference)`. Multiple partial refund events for the same order contribute their event amounts to `refund_amount` but the order contributes once to `refunded_order_count`. Coverage dates and source labels come from the qualifying event stream. Missing event days remain missing, not zero.

These source-event metrics are separate from daily aggregate `return_count` and `refunded_amount` measurements. Neither source is netted against attributed revenue or paid value, and the readout remains descriptive rather than causal.
