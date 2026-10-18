# Sprint 31: campaign portfolio conflict review

The portfolio view is read-only and limited to draft campaigns visible through the caller's `crm.campaign:view` organization scope. A caller chooses a timezone-aware review window.

A schedule conflict is reported only when two campaigns reference the same saved segment and their scheduled intervals overlap. Segments with different IDs may still contain common customers; this report does not infer that overlap. Campaigns without both schedule endpoints are counted as unscheduled. Large result sets indicate truncation.

The view is for planning review. It does not change campaign plans, activate a campaign, materialize recipients, or send messages.
