# Sprint 188: learning action completion rate

The campaign decision queue now reports the percentage of target-plan learning actions marked completed:

`completed / (completed + open or in-progress) × 100`

The value is `null` when the viewer lacks work-item visibility or when the target plan has no tracked actions. It describes follow-through only; it does not assess whether an action improved campaign results.
