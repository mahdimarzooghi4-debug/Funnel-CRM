# Sprint 95: campaign portfolio decision queue

Adds `GET /api/v1/crm/campaigns/decision-queue`, a paginated cross-campaign view of target plans overlapping a requested date range. It prioritizes plans with missed metrics, target metrics without data, and recorded-day coverage below 80%, then reports the evidence counts that caused review to be surfaced.

The queue uses existing campaign target evaluations and campaign-view scopes. It does not infer missing days as zero, include ROAS in its ranking, claim causal attribution, or issue budget/pause/continue recommendations. The single-campaign decision workspace remains the place to inspect commerce outcomes and ROAS. Queue access is audited.

Integration coverage exercises the decision workspace and queue against the same campaign plan, verifying the missed-target and low-coverage flags.
