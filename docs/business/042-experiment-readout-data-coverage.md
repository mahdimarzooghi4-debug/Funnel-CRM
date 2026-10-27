# Experiment readout data coverage

## Purpose

Campaign experiment results must show how much source data supports each reported metric. A single total or rate can hide missing days and unequal reporting coverage between variants.

## Readout requirements

- For the experiment's complete inclusive date range, show expected calendar days, days with qualifying observations, missing days, coverage percentage, and the exact missing dates for each primary metric and guardrail, per variant.
- Show each variant's coverage difference from control in percentage points for the same metric, so unequal reporting coverage is visible without introducing an arbitrary pass/fail threshold.
- Add an experiment-level summary for each primary and guardrail metric with the number of variants, number with missing days, minimum and maximum coverage, and the spread in percentage points.
- In that summary, identify each variant by its label and control role, with its coverage, missing dates, and qualifying source labels. This makes the lower-coverage group and the underlying source trail visible without comparing separate response sections.
- Classify completeness as complete only when every variant has 100% coverage, unavailable when every variant has 0% coverage, and partial otherwise. Classify coverage balance as equal only when all variants have the same coverage percentage; these labels describe source coverage and do not judge experiment quality.
- A day counts as observed only when that day's measurement row contains the field or fields needed to calculate that metric. For rates, both numerator and denominator are required. For cost and ROAS metrics, the relevant amount and outcome fields must be present in the selected currency.
- Show the source labels associated with qualifying observations so the reviewer can trace the reported values to the inputs recorded in the CRM.
- Keep the result descriptive. Coverage does not establish that groups were comparable or that an observed difference was caused by the campaign variant.
- Do not infer expected data cadence outside the experiment period or invent unrecorded observations.

## Interpretation

Missing dates indicate that no qualifying daily observation was recorded for that metric and variant on that date. They do not prove that the campaign had no activity. Managers should review coverage alongside the allocation method, known limitations, and the measurement sources before interpreting differences.

## Export

Authorized campaign viewers can download the readout as UTF-8 CSV for spreadsheet review. Each row represents one metric for one variant and includes experiment context, observed values, coverage, missing dates, and source labels. The export uses the same tenant and organization authorization as the readout, records an export audit event, and protects user-entered text from spreadsheet formula execution.
