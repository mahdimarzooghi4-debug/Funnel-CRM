# Sprint 58: identity-scoped workspace selection

Replaces manual workspace and organization UUID entry in the budget-scenario comparison workspace.

- The workspace selector lists active memberships for the identity verified by upstream authentication.
- The organization selector lists only units where the active member has both campaign-view and budget-scenario-view permission.
- Workspace discovery uses additional PostgreSQL SELECT policies that filter through transaction-local issuer and subject claims. The ordinary tenant isolation policies remain in place; no privileged function or broader runtime grant is used.
- Existing tenant-scoped endpoints continue to verify active membership and permissions on every request. Selector values remain convenience choices, never authorization.
- No write, activation, campaign send, or budget operation is added.

## Validation

Pending exact-head CI and database migration tests.
