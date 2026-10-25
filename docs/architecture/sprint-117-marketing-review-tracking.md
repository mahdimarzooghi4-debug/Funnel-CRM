# Sprint 117: marketing review and follow-up tracking

The marketing manager workspace now loads its organization- and period-scoped marketing learning portfolio after generating a campaign report. It summarizes planned/evaluated reviews and, when the caller has work-item view access, linked task counts and per-review status, assignee presence, and due date.

The page first requests the portfolio with linked work items and falls back to the review-only portfolio when work-item details are not authorized. It does not expose raw membership identity, infer task completion, or change review/task state. Empty, unavailable, and permission-limited views are distinguished.

Validation: browser client test verifies scope filters, workspace header, portfolio summary, and task visibility; Python syntax compilation and `git diff --check` pass locally.
