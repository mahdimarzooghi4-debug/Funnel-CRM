# Sprint 198: portfolio period comparison

A marketing manager can compare recorded campaign measurements across two explicitly selected, non-overlapping date windows. The endpoint reports calendar-window lengths, campaign and measurement coverage, impressions/clicks/leads/conversions totals, observed-day counts per metric, absolute changes, and percentage changes when a non-zero baseline is available.

Recorded spend and explicitly linked paid/refunded commerce amounts are compared separately by currency. Commerce-event access is checked independently from campaign measurement access and the response reports complete, partial, or unavailable commerce scope. Both windows are bounded to 366 days; the baseline must end before the comparison window begins.

The output is descriptive. It does not adjust for differing campaign mix or period length, assert causal attribution, convert currencies, or issue automatic recommendations. Managers should read changes together with calendar-window length and data coverage.
