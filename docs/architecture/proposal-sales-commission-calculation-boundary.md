# Proposal: Sales commission calculation boundary

- Status: approved for implementation on 2026-10-25
- Related business decision: `docs/business/132-sales-incentive-and-commission-plans.md`
- Purpose: resolve the data source and rule needed before commission amounts are calculated.

## What the current CRM data supports

- `CRMOpportunity` records an amount, currency, pipeline stage, and expected close date. A pipeline stage can be marked won, but the record has no seller membership or actual close timestamp. It is evidence of a CRM-recorded win, not necessarily a paid sale.
- `CRMProductCommerceEvent` records paid and refunded order events, amount, currency, and event time. It has no seller membership, so the event cannot currently be attributed to an individual salesperson.
- The CRM has no commission-plan, seller-attribution, or proposed-commission ledger yet.

## Approved choices

1. **Commission basis:** paid order and refund events from connected products.
2. **Seller attribution:** the selling product sends the responsible CRM membership on each event. Split attribution is outside the first version.
3. **First calculation rule:** a plan-defined percentage of net paid sales, grouped by currency without conversion.

## Calculation semantics

For the selected period, calculate each seller's basis as paid events minus refunded events, separately for each currency. A refund is attributed to the seller named on that refund event and affects the period in which the refund occurred. Rates are supplied by the selected plan; missing or ambiguous plans produce no calculation. The stored proposal retains six decimal places, matching the source amount precision. This is a proposal amount, not an approved payable amount.

Events without seller attribution remain valid commerce records but are excluded from seller totals and reported as unattributed. Plan-specific membership scope, when present, matches only that seller; otherwise the plan is organization-wide. Event times use UTC period boundaries until workspace timezone settings are implemented.

## Implementation boundary after approval

- Version each plan and preserve the exact rule version used by each calculation.
- Snapshot the source event identifiers and amounts used for each proposal.
- Keep calculation proposals, approved amounts, and payments distinct.
- Preserve currencies independently; never infer exchange rates.
- Audit plan changes and proposal generation without claiming that a proposal was financially approved.
- Do not add default rates or calculate when the selected plan lacks a rule.
- Do not transfer funds, create payroll instructions, or mark a proposal as financially approved.
