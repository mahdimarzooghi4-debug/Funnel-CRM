# Sprint 148: experiment design context

Campaign experiment records now require an allocation-method description and may include known design limitations. Both fields are returned with the experiment and its readout and are included in the creation audit event. Existing experiments receive `unspecified` during migration to avoid inventing a method for historical records.

The allocation method is manager-entered context; CRM does not assign people to variants or infer randomization. Readouts remain descriptive observations. Their differences are not labeled causal merely because an allocation method has been recorded.

This supports the approved requirements for traceable assignment method and visible risks in [Offer effectiveness experiments](../business/041-offer-discount-effectiveness-experiments.md).
