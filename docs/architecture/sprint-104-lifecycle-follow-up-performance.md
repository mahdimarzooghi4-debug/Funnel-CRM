# Sprint 104 — lifecycle follow-up performance report

## Goal

Give marketing managers an operational view of recorded follow-up outcomes by reporting period, recorder, and channel.

## API

`GET /api/v1/crm/work-items/lifecycle-review-performance`

Required inputs are `organization_unit_id`, timezone-aware `start_at`, and timezone-aware `end_at`. The window includes its start and excludes its end. Results contain total outcomes, distinct work items and profiles, plus grouped counts by outcome recorder, channel, and outcome code. Only outcomes attached to lifecycle-review work items in the authorized organization are included. Each report view is audited.

## Interpretation

The report describes human-recorded outcomes within the selected time window. It does not infer sentiment or establish that a channel or staff member caused a customer or revenue result.

## Verification

Integration coverage checks a bounded window, aggregate counts, recorder/channel/outcome grouping, exclusive end-window semantics, and invalid-window rejection.
