# Sprint 70: campaign target outcomes in budget reports

Bring the existing authorized campaign-target portfolio evaluation into the budget comparison report. Show only target plans matching the report's exact date range and campaigns common to the selected scenarios. Reuse the target evaluator's status, actual, target, and recorded-day coverage; do not infer outcomes from missing values.

Keep the budget report available if the target portfolio cannot be loaded. The CSV should include the same target status and coverage context. Exact-period plans are required; a missing plan is not a failed target.

## Validation

Initial implementation commit `e56a4dcd0f35eace554b799bcc4aff9adcf4545f` exposed a CSV assertion mismatch. After correcting the assertion, commit `9fedafc178b6c8c3c5f14f2e61cf13cff9b30eeb` passed GitHub Actions run `39960521653`: 94 Python tests passed (3 existing warnings), and the budget comparison browser behavior test passed.
