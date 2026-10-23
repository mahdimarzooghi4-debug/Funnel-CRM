# Sprint 64: evidence gap worklist

Add a campaign-level worklist showing exactly which evidence fields are absent for each overlapping campaign: recorded spend, leads, and conversions. Hide campaigns with complete evidence, and show an explicit empty state when no gaps remain.

Use null or absent observations as missing evidence; never interpret them as zero. Render campaign/channel names as text and include one CSV row per missing field to support follow-up outside the report.

## Validation

Exact head `8c6a9e9549967e9954156034d488733422cca644`: GitHub Actions run `39955643671` succeeded; Alembic passed, pytest reported 94 passed with 3 warnings, and the Node client behavior test passed.
