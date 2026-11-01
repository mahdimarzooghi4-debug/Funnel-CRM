# Sprint 144 — Marketing offer planning drafts

Implements the approved marketing offer planning decision (`docs/business/040-sales-offer-and-discount-planning.md`) as an organization-scoped CRM capability, separate from customer-specific sales quotes.

Drafts can record an objective, configurable offer type, optional catalog item and campaign, audience description, channel, location/store scope, schedule, eligibility conditions, owner, and success metric. Drafts are editable with optimistic version checks and audit events. The UI does not activate an offer, change a price or discount, send a campaign, or access orders, payments, inventory, or customer records.

Access uses dedicated view, create, and update permissions. Catalog and campaign references are validated against their own permissions and the same organization scope. No universal discount type, amount, margin, or eligibility rule is imposed.
