# Sprint 140 — Catalog categories and search

Adds an optional category label to each organization-scoped product or service. Category changes participate in the existing optimistic item version and audit trail. Catalog list endpoints can filter by category and search item name/code. The Persian catalog workspace exposes category editing and debounced name/code search.

Category labels remain simple labels within each organization; this sprint does not introduce a global taxonomy, hierarchy, package composition, or pricing behavior.

Validation: PostgreSQL migration, tenant-isolated catalog integration test, workspace route test, Python compile, JavaScript syntax check, and Alembic head check.
