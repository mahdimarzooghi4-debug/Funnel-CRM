# Sprint 178: campaign decision commerce by source product

The campaign decision workspace now reports paid, refunded, and net commerce outcomes by source product and currency, including event/order counts and net paid amount per paid order.

Source-product outcomes are descriptive. Campaign spend remains reported by currency at campaign level because the available spend data does not identify a source product. No product-specific return multiple or causal attribution is inferred.

Validation: the decision-workspace regression test checks two source products in USD and an independent EUR outcome while preserving the campaign-level currency totals.
