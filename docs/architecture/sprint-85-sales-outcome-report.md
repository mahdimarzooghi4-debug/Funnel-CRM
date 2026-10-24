# Sprint 85: recorded sales outcome report

Provide an authorized, audited report of opportunities that entered a manager-configured won or lost stage during a selected period. Results are grouped by pipeline and terminal stage, with priced and unpriced counts and currency-preserving amount totals.

The report is based on append-only opportunity create/update audit events and explicit pipeline outcome configuration. It reports stage-entry events, not a deduplicated customer win rate; repeated closing/reopening transitions can be reported as separate decisions. It does not infer outcomes from stage names or provide loss reasons.
