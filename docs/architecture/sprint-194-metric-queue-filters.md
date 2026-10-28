# Sprint 194: metric-specific queue filters

The campaign decision queue can be narrowed to plans that track a selected target metric and optionally to a result status (`met`, `not_met`, or `no_data`). A status without a metric key matches plans with at least one visible metric in that status.

Metric filtering is applied after scope authorization and ranking and before pagination. Commerce-dependent metrics are only present for viewers with the required commerce permission.
