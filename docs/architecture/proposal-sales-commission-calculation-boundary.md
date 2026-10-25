# Proposal: Sales commission calculation boundary

- Status: proposal; not approved
- Related business decision: `docs/business/132-sales-incentive-and-commission-plans.md`
- Purpose: resolve the data source and rule needed before commission amounts are calculated.

## What the current CRM data supports

- `CRMOpportunity` records an amount, currency, pipeline stage, and expected close date. A pipeline stage can be marked won, but the record has no seller membership or actual close timestamp. It is evidence of a CRM-recorded win, not necessarily a paid sale.
- `CRMProductCommerceEvent` records paid and refunded order events, amount, currency, and event time. It has no seller membership, so the event cannot currently be attributed to an individual salesperson.
- The CRM has no commission-plan, seller-attribution, or proposed-commission ledger yet.

## Decisions required

1. **Commission basis:** use a won opportunity, a paid order/refund event, or let each plan select one of these sources.
2. **Seller attribution:** use the opportunity's owner, require the selling product to send the seller membership on each order event, or support explicit split attribution.
3. **First calculation rule:** use a percentage of net paid sales (paid events less refunds, per currency, with no currency conversion), a fixed amount per paid order, or a manager-defined rule set.

## Proposed starting point

Use paid order/refund events as the commission basis, require each connected sales product to provide the responsible CRM membership for a paid event, and calculate a plan-specific percentage of net paid amount separately for each currency. Refunds reverse the corresponding basis when they occur. Keep proposal calculation separate from financial approval and payment; do not transfer funds or export a payroll instruction.

This starting point is a recommendation, not a stored decision. It favors recorded transaction facts over pipeline estimates. Before implementing it, define how partial refunds, split sellers, event corrections, and commissions after a seller's access is removed are handled. If the selected source is opportunities instead, the team must define how a won stage is dated and attributed.

## Implementation boundary after approval

- Version each plan and preserve the exact rule version used by each calculation.
- Snapshot the source event identifiers and amounts used for each proposal.
- Keep calculation proposals, approved amounts, and payments distinct.
- Preserve currencies independently; never infer exchange rates.
- Audit plan changes and proposal generation without claiming that a proposal was financially approved.
- Do not add default rates or calculate when the selected plan lacks a rule.
