# Sprint 149: experiment audience snapshot

When an experiment is created, CRM captures the shared saved segment used by its variant campaigns: segment ID, display name, and criteria. The experiment read model keeps that snapshot even if the live segment is later edited or deactivated. Existing experiments remain `null` because their historical criteria cannot be reconstructed safely.

All variant campaigns must continue to use the same segment, objective, channel, and organization scope. This stores the criteria used to define the eligible audience; it does not materialize individual people, assign them to variants, or prove that the execution platform honored the segment.

This supports traceable population definition in [Offer effectiveness experiments](../business/041-offer-discount-effectiveness-experiments.md) while respecting customer-data permissions.
