# Sprint 196: campaign decision queue CSV export

Marketing managers can export the complete decision queue after applying the same date, organization, status, attention-reason, and metric filters used by the API. The export includes campaign and target-plan context, attention reasons, action progress, permitted commerce outcome buckets, and available metric target/actual/status values.

The export is capped at 5,000 target plans; narrower periods or filters can be used when the result exceeds the cap. Tenant and organization authorization and optional commerce/work-item permissions are inherited from the decision queue. CSV text is protected against spreadsheet formula execution, and the download uses UTF-8 with a BOM for common spreadsheet applications. Existing evidence limitations still apply: this export is descriptive, not causal attribution or an automatic recommendation.
