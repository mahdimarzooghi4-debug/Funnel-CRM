# Sprint 160: order-linked refund rate in experiment readouts

Campaign experiments can report `refunded_order_rate_percent` from source commerce events explicitly linked to each variant campaign. The denominator is the unique `(source_product, order_reference)` set with a `paid` event; the numerator is the intersection of that set with unique orders carrying a `refunded` event in the experiment window. Repeated paid events and partial refunds do not multiply either order count.

The metric is unavailable when there are no recorded paid orders. Coverage describes dates with paid-event evidence and lists the contributing source products. The metric requires `crm.campaign:view` and `crm.commerce_event:view`, has no currency parameter, and remains descriptive: missing refund events do not prove that no refunds occurred, and refunds after the experiment window are not included.
