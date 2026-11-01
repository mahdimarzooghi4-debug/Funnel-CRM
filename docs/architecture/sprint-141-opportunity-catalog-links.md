# Sprint 141 — Opportunity catalog references

Sales opportunities can reference products and services from the authorized organization catalog. The API checks both opportunity-update and catalog-view permissions, enforces tenant and organization boundaries, and captures a snapshot of the catalog item identity and version so later catalog edits do not rewrite the opportunity history.

The link is descriptive. Opportunity amount and currency remain separately managed; this sprint does not create a quote, price adjustment, discount, order, or financial commitment.

Validation covers RLS migration, permission-scoped attach/list behavior, stale-version and duplicate rejection, and application route registration.
