# Sprint 197: portfolio financial rollups by currency

The filtered campaign decision queue summary now includes recorded spend and explicitly linked paid/refunded commerce outcomes grouped by currency. It reports amounts, event/order counts, and spend measurement counts without calculating a combined return multiple.

The rollup uses the union of the selected target-plan date windows and queries the underlying measurement and commerce records once. This avoids adding the same fact twice when one campaign has overlapping target plans. Commerce rows are included only for organization units where the caller has commerce-event access; the summary states whether commerce scope is complete, partial, or unavailable. Totals remain descriptive and do not establish causal attribution or accounting revenue.
