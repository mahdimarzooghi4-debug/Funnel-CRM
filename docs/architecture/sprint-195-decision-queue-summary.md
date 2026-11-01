# Sprint 195: campaign decision queue portfolio summary

The decision queue now returns an aggregate summary for the full filtered result set, independently of the requested page. Managers can see:

- plan and distinct campaign counts;
- counts by queue status;
- counts by attention reason;
- per-metric counts of met, missed, and no-data target evaluations.

All summary values follow the same tenant, organization-unit authorization, date-window, and filter scope as the returned queue. Pagination does not change the summary. Metrics are counted only where a target evaluation exists. These are descriptive counts, not causal performance conclusions or automated recommendations.
