# Sprint 55: budget scenario performance context

Budget scenarios can now be reviewed against recorded campaign outcomes for a manager-selected period.

- The read-only performance context compares planned allocation with actual recorded spend only in the allocation's currency.
- Recorded spend in other currencies remains visible but is not converted or used to calculate variance.
- Leads and conversions are reported with observed-day coverage. Missing records remain unknown, not zero.
- The response includes canonical KPI definitions and states that it applies no causal attribution or automatic recommendation.
- Context reads require scenario-view and campaign-view permissions and create an audit event.
