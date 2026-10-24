# Sprint 34: campaign measurement ledger

## Purpose

Record observed daily campaign results from an explicitly named reporting source, then summarize a chosen date range. These records do not imply that Funnel sent messages or independently verified the source.

## Recorded observations

One row per campaign and calendar day stores any available impressions, reach, clicks, responses, leads, conversions, actual spend, and attributed revenue. Unreported metrics stay null; explicit zero is retained as a reported value. A second write to the same campaign and day replaces the observation, so a corrected report does not double-count.

Actual spend and attributed revenue each require a currency and are aggregated separately by currency. No currency conversion or margin calculation is performed. Attribution method is not inferred; the source label remains visible in the report.

## Derived rates

The date-range summary calculates click-through rate only on days where clicks and impressions were both reported, lead rate only where leads and clicks were reported, and conversion rate only where conversions and clicks were reported. Metric coverage days are returned alongside totals so partial reporting is visible. A rate is null when no paired data exists or its denominator is zero.

## Access and boundaries

- Reading requires `crm.campaign:view`; recording and correcting require `crm.campaign:manage`.
- Rows are isolated by tenant RLS and constrained to the campaign's organization unit by a composite foreign key.
- Measurement dates can be summarized over a maximum 366-day inclusive range.
- Campaign planned budgets remain unchanged. This feature does not activate campaigns, send communications, collect customer-level attribution, approve spending, or verify external reports.
