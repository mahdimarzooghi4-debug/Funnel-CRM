# Sprint 53: metric context in campaign decisions

The campaign decision workspace now returns the glossary definition next to every evaluated metric, so a consuming screen can render definitions without a second request.

- `metric_definitions` uses the same keys as the workspace `metrics` object. The plan's `spend` metric is linked to the canonical `actual_spend` definition.
- `coverage_definition` explains how to interpret the recorded-day coverage percentage shown for each metric.
- The endpoint retains its existing campaign and commerce permissions. No new values, calculations, or recommendations are introduced.
- Integration coverage verifies the response links the spend and commerce metrics to the right definitions.
