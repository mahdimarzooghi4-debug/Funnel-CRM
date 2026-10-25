# Sprint 115: variance-to-review handoff

The campaign-level target variance table can now open a human review for a campaign and metric. The manager receives a factual evidence draft with the reporting period, target, recorded actual, coverage, and variance where complete coverage permits it. The manager must review or edit that text and provide the next investigation/corrective action before submitting.

The page submits to the existing tenant-scoped marketing learning review API, which enforces `crm.campaign:manage`. After the review is saved, the manager can explicitly request a separate follow-up work item through the existing review endpoint; that endpoint enforces `crm.work_item:create` and creates it unassigned without a due date. Neither step approves resources, alters targets or budgets, or executes an external action. Incomplete-period evidence is explicitly labeled as incomplete and its variance remains uncomputed.

Validation: browser client test covers opening the review form, the evidence draft, workspace-scoped review creation, separate work-item creation, and successful completion; Python syntax compilation and `git diff --check` pass locally.
