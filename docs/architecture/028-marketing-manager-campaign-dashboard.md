# Marketing manager campaign dashboard

`GET /api/v1/crm/analytics/marketing-manager/campaigns?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` composes the authorized campaign performance, channel, configured audience segment, measurement-quality, and target-attainment reports for the same inclusive reporting period.

The dashboard presents currency-separated budgets, spend, attributed revenue, and same-currency efficiency measures; campaign count totals; channel and segment breakdowns; campaign-day and metric-day coverage; target outcomes and variance; and up to 50 manager signals. Target attainment is included only for plans whose period exactly matches the requested dates, following the underlying target-portfolio contract. Commerce outcomes remain subject to the existing commerce permission rules.

The selected period is limited to 366 days. Campaign reports inherit the 500-campaign cap and provide truncation flags; manager signals are separately capped. The dashboard performs an aggregate audit entry and invokes the component reports, which each retain their own read audit. Figures describe recorded data and do not establish that a campaign caused a sales outcome or that a signal should trigger an automatic action.

## CSV export

`GET /api/v1/crm/analytics/marketing-manager/campaigns/export.csv` returns a UTF-8 CSV with a byte-order mark for spreadsheet compatibility. The file uses a `record_type` column to distinguish metadata, summary, channel, segment, coverage, target, manager-signal, and commerce rows. It includes a report-definition version and generation timestamp. The export request is audited with its period, format, version, timestamp, and row/column counts; the generated report data is not stored as a durable snapshot. Untrusted text cells are prefixed when they begin with spreadsheet formula characters.

## Immutable snapshots

`POST /api/v1/crm/analytics/marketing-manager/campaigns/snapshots?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD` stores a complete dashboard result with its report version, period, creation time, and SHA-256 content hash. This captures the report as observed at creation time, so later campaign edits do not rewrite past reviews.

`GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshots` lists metadata for snapshots created by the current identity in the active workspace. Use `limit` (1–100) and `offset` for pagination. `GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshots/{snapshot_id}` returns the saved dashboard only to its creator and verifies the stored hash before returning it. The database enforces tenant row security and rejects tenant-scoped snapshot updates or direct deletion while allowing workspace deletion cascades. Snapshot creation and reads are audited without copying report contents into the audit log.

## Comparing snapshots

`GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-comparisons?baseline_id={uuid}&current_id={uuid}` compares two snapshots created by the current identity in the active workspace. Both snapshots must have the same report period and definition version, and both hashes are verified before comparison. The response lists numeric metric paths with previous/current values, absolute and percentage changes, and explicit added/removed states; a missing value is never treated as zero. Comparison access is audited with snapshot hashes and the number of changed metrics.

The same comparison is available as `GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-comparisons/export.csv` with the same `baseline_id` and `current_id` query parameters. It includes snapshot IDs and hashes, period/version metadata, and one row per changed metric. Text cells are protected against spreadsheet formula execution, and the export is audited with its row and column counts.

## Manager decisions and follow-up

A manager can record an action against a snapshot using `POST /api/v1/crm/analytics/marketing-manager/campaigns/snapshots/{snapshot_id}/actions`. Each action has a title, decision note, optional due date, and optional active workspace assignee. The snapshot worklist at `GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions` shows actions created by or assigned to the current member and supports status filtering. An assignee can view and close the action; dashboard snapshot access keeps its existing creator scope.

`PATCH /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action_id}` records a completed or cancelled status with an outcome. An action can transition once from open to a terminal status; database constraints and a transition trigger enforce the rule. Creation, worklist reads, and closure are audited.

## Action tracking analytics

`GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/analytics` summarizes actions created by or assigned to the current member. It reports open/completed/cancelled counts, overdue open actions, open actions due within seven days, completion rate among closed actions, and average days to closure. A null completion rate means there are no closed actions yet. The overdue and due-soon counts use the database's current date; the read is audited.

## Verifying follow-up outcomes

`POST /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action_id}/verifications` records an observed numeric metric from the action's baseline snapshot against a later snapshot. The snapshots must share a reporting period and definition version, and both hashes are verified. The manager may record an expected direction; the response reports whether the observed movement matched it. Verification records are append-only and can be listed from `GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action_id}/verifications`. The result describes an observed change and does not establish that the action caused it.

## Learning from recorded action outcomes

`GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/verification-analytics` aggregates recorded metric observations by metric path. It reports observation counts, increase/decrease/no-change counts, average observed movement, expected-direction matches, and the match rate where an expected direction was supplied. The aggregation includes only verifications for actions created by the current identity.

`GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/verification-analytics/export.csv` exports the summary and metric groups as UTF-8 CSV. The report describes recorded observations and does not establish that actions caused the measured changes.

## Action deadline alerts

`GET /api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/alerts` returns current overdue, due-today, and next-seven-day counts plus the matching open actions. It is computed when requested from the database's current date, so no external notification provider or scheduled delivery is required. The result is scoped to actions created by or assigned to the active member and is audited.

## Campaign budget pacing

`GET /api/v1/crm/analytics/marketing-manager/campaigns/budget-pacing?period_start=YYYY-MM-DD&as_of=YYYY-MM-DD` compares campaign spend recorded from the selected period start through the as-of date with expected spend under a linear distribution of the planned budget across the campaign's inclusive scheduled dates. It reports ahead/behind/on-pace states, variance, schedule completeness, and spend in other currencies separately. A missing same-currency spend observation stays null and is reported as `no_spend_data`; it is not treated as zero. The report is descriptive and audits its period and pacing counts.

`GET /api/v1/crm/analytics/marketing-manager/campaigns/budget-pacing/export.csv` provides a spreadsheet-ready export with the same period, currency separation, and pacing basis.

`GET /api/v1/crm/analytics/marketing-manager/campaigns/budget-pacing/alerts?period_start=YYYY-MM-DD&as_of=YYYY-MM-DD&variance_threshold_percent=10&limit=100` lists campaigns whose absolute spend variance from expected pace meets the requested percentage threshold. The threshold must be between 0 and 100; campaigns with missing observed spend or zero expected spend do not produce percentage alerts. The response states the threshold basis and whether the result was truncated, and the request is audited.

`GET /api/v1/crm/analytics/marketing-manager/campaigns/budget-pacing/alerts/export.csv` exports the threshold-filtered alert list as UTF-8 CSV with a spreadsheet-compatible byte-order mark. It includes the selected period, threshold, campaign pacing values, and whether the alert list was truncated. Campaign names and statuses are protected against spreadsheet formulas, and the export request is audited.
