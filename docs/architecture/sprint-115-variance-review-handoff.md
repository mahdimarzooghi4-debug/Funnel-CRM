# Sprint 115: variance-to-review handoff

The campaign-level target variance table can now open a human review for a campaign and metric. The manager receives a factual evidence draft with the reporting period, target, recorded actual, coverage, and variance where complete coverage permits it. The manager must review or edit that text and provide the next investigation/corrective action before submitting.

The page submits to the existing tenant-scoped marketing learning review API, which enforces `crm.campaign:manage`. It does not create a work item, approve resources, alter targets or budgets, or execute an external action. Incomplete-period evidence is explicitly labeled as incomplete and its variance remains uncomputed.

Validation: browser client test covers opening the review form, the evidence draft, workspace-scoped POST payload, and successful completion; Python syntax compilation and `git diff --check` pass locally.
