# Sprint 138: Product and service catalog foundation

Each authorized organization unit can maintain its own product and service catalog. Items have stable organization-scoped codes and optimistic version checks for metadata updates. Prices are append-only versions with an explicit currency and optional inclusive effective dates; historical prices remain available for traceability. Inactive items remain readable but cannot receive new prices.

The API enforces tenant isolation, organization-scoped `crm.catalog:view` and `crm.catalog:manage` permissions, and audit records for changes. This foundation does not infer tax, inventory, discount, or quote rules.

Validation covers tenant-scoped permissions, duplicate codes, item version conflicts, immutable price history, effective date validation, and active/inactive behavior. PostgreSQL CI applies the RLS migration and runs integration tests.
