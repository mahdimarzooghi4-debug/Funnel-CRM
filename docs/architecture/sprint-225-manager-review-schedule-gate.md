# Sprint 225: Current manager review required for scheduling

Campaign scheduling now requires the latest readiness review decision to be `proceed_to_schedule`. A `hold` or `request_changes` review blocks the lifecycle transition.

The review stores a basis snapshot containing campaign version, audience segment, channel, communication purpose, schedule, approved/pending asset counts, and readiness-check statuses and counts. Before scheduling, the API recomputes that basis and rejects stale decisions. Any campaign edit requires a new manager review, including edits later reverted; asset or audience/consent changes also require a fresh review when they change the snapshot.

The scheduler still enforces its existing schedule, active-audience, and content-approval checks. A manager decision never sends a campaign. A stale or non-proceed review returns 409 and leaves the campaign in draft.
