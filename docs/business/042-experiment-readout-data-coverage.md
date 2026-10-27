# Experiment readout data coverage

## Purpose

Campaign experiment results must show how much source data supports each reported metric. A single total or rate can hide missing days and unequal reporting coverage between variants.

## Readout requirements

- For the experiment's complete inclusive date range, show expected calendar days, days with qualifying observations, missing days, coverage percentage, and the exact missing dates for each primary metric and guardrail, per variant.
- A day counts as observed only when that day's measurement row contains the field or fields needed to calculate that metric. For rates, both numerator and denominator are required. For cost and ROAS metrics, the relevant amount and outcome fields must be present in the selected currency.
- Show the source labels associated with qualifying observations so the reviewer can trace the reported values to the inputs recorded in the CRM.
- Keep the result descriptive. Coverage does not establish that groups were comparable or that an observed difference was caused by the campaign variant.
- Do not infer expected data cadence outside the experiment period or invent unrecorded observations.

## Interpretation

Missing dates indicate that no qualifying daily observation was recorded for that metric and variant on that date. They do not prove that the campaign had no activity. Managers should review coverage alongside the allocation method, known limitations, and the measurement sources before interpreting differences.
