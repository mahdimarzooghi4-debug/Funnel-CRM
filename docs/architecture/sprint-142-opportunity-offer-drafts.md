# Sprint 142 — Opportunity offer drafts

Adds an authorized API for creating and listing non-binding offer drafts on sales opportunities. Draft lines must reference catalog items already linked to that opportunity, use an explicitly selected catalog price version that is effective today, and preserve item, item-version, price-version, quantity, currency, and amount snapshots. Totals are grouped by currency with no exchange-rate conversion.

Offer drafts require dedicated `crm.offer:create` and `crm.offer:view` permissions in addition to catalog visibility. Draft creation does not change opportunity amount, edit catalog prices, apply discounts/taxes, send an offer externally, accept terms, or create an order or contract.

Validation covers tenant RLS, permission checks, line and price snapshots, totals by currency, and application route registration.
