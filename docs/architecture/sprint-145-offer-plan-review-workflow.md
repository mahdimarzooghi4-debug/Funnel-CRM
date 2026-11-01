# Sprint 145 — Marketing offer plan review workflow

Adds explicit review decisions for marketing offer plans: an authorized reviewer can approve a draft in CRM or request changes with a required note. Review has its own `crm.offer_plan:approve` permission and increments the optimistic version. A requested-change plan must be edited before it returns to draft and can be reviewed again. Approved plans are read-only; create a separate draft for a new proposal.

Every decision and edit is audited with the actor, scope, status, version, and review note. CRM approval does not activate the offer in a store, sales channel, or campaign; it does not change prices or discounts, send anything, or create orders or payments. Activation remains a separate future permission and connected-product action.
