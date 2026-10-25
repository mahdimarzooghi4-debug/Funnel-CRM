# Sprint 126: search reusable marketing lessons

The marketing learning portfolio supports a case-insensitive search over recorded lessons learned. Search is applied in the API before pagination, so result totals and pages stay consistent. The normalized query is returned with the report and recorded in the portfolio audit event.

The search remains inside the caller's tenant, campaign-view scopes, organization unit, and selected period. SQL wildcard characters in the query are treated literally; unreviewed or planned records without a lesson do not appear as matches.

Validation covers case-insensitive matching, whitespace normalization, literal wildcard handling, and sending the search from the browser workspace.
