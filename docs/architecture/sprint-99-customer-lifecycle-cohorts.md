# Sprint 99: customer lifecycle cohort analytics

Adds `GET /api/v1/crm/analytics/customer-lifecycle`, an aggregate marketing decision view grouped by each active profile's current lifecycle stage and profile kind. For a selected date range it reports linked profile activities, associated opportunities, and profile-linked paid/refund commerce facts, including currency-separated order and amount metrics.

The endpoint intersects profile, opportunity, and commerce authorization at organization scope, supports paginated cohort groups, excludes archived and merged profiles, and audits report access. Cohort stage is a current snapshot; historical stage at event time is not available. Event relationships are observed associations, not causal attribution, and currencies are not converted or combined.

Integration coverage verifies stage grouping, distinct profiles, activity/opportunity linkage, paid/refund separation, currency isolation, permission denial, and audit evidence.
