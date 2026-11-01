# Sprint 199: campaign outcomes by connected product

The campaign decision queue summary now breaks paid and refunded commerce outcomes down by connected source product and currency. Each row reports event and order counts, paid/refunded/net amounts, and each source's share of recorded paid or refunded amounts within the same currency.

The breakdown is computed from the unique linked commerce-event rows selected by the filtered target-plan date windows, so overlapping plans do not duplicate events. Only rows in commerce-authorized organization units are included. Shares describe recorded event amounts; they are not causal marketing attribution, accounting revenue, or a cross-currency comparison.
