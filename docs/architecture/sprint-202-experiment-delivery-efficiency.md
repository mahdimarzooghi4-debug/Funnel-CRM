# Sprint 202: experiment delivery efficiency

Experiment readouts now show the primary recorded metric per assigned count and per exposed count, along with each rate's difference from the control. Ratios are omitted when the primary metric or denominator is unavailable, and zero denominators never produce a rate. These descriptive measures help managers inspect delivery volume alongside outcomes; they do not establish causality or identify a winner.

CSV readouts include these fields for primary-metric rows. Guardrails and delivery-count rows leave them blank because they use different metric roles.
