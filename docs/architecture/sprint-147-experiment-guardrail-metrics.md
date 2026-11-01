# Sprint 147: campaign experiment guardrail metrics

Campaign experiments may configure up to eight guardrail metrics alongside the primary metric. A guardrail can use the existing campaign measurement catalog and, where required, a currency. Duplicate metrics and a guardrail that repeats the primary metric are rejected.

The experiment readout reports each guardrail for every variant, including its observed value, difference and percentage change from control, data coverage, and `available` or `no_data` status. These measures remain descriptive observations; they do not establish causal impact or automatically pass/fail a variant. The primary metric and guardrails appear together so a conversion increase does not hide a change in spend or ROAS.

This implements the guardrail reporting requirement in [Offer effectiveness experiments](../business/041-offer-discount-effectiveness-experiments.md). The migration adds an empty JSON array for existing experiments, preserving compatibility.
