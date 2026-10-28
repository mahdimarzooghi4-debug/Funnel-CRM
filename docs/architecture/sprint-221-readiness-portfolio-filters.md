# Sprint 221: Campaign readiness portfolio filters

The campaign readiness portfolio accepts optional channel and communication-purpose filters:

- `channel`: exact campaign channel match.
- `communication_purpose_key`: exact purpose match.

Filters apply before the total count and pagination, so `total_draft_campaigns`, `has_more`, page-level readiness counts, and items all describe the same filtered set. The applied filters are included in the portfolio review audit event.

These filters work alongside the optional organization-unit scope and existing page-size/offset parameters. No filter broadens the caller's authorized tenant or organization scopes.
