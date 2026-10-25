# Sprint 114: campaign-level marketing target variance

The marketing manager workspace now lists target and observed values for each campaign and additive count metric (impressions, clicks, leads, conversions). Complete-period comparisons show arithmetic variance and incomplete periods show the recorded value, target, and day coverage without presenting a partial-period gap as a final variance.

Rows are ordered with complete-period shortfalls first, followed by other complete-period rows and incomplete coverage. The CSV includes the same campaign-level evidence. This is descriptive analysis only: a numeric gap does not establish why performance differed.

Validation: browser client behavior test, Python syntax compilation, and `git diff --check` pass locally.
