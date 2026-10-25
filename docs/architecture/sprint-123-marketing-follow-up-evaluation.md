# Sprint 123: evaluate marketing follow-up from the review portfolio

Managers with `crm.campaign:manage` can now evaluate a planned marketing learning review from its portfolio row. The form lists target periods for the same campaign that begin after the reviewed baseline and asks the manager to record observed effectiveness and a lesson learned.

Submission uses the existing review evaluation endpoint. That endpoint verifies the target plan belongs to the campaign, follows the baseline period, and contains observed measurement data. The interface treats the assessment as manager-authored and does not claim that a measured change proves causation. The portfolio refreshes after a successful evaluation.

Validation covers permission-gated capability, target-period selection, and the evaluation request payload. Local browser client, syntax compilation, and diff checks pass; CI runs the database authorization and observed-data rules.
