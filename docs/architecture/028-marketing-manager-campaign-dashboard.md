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
