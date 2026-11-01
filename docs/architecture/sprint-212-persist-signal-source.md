# Sprint 212: Persisted campaign signal source

Campaign-generated work items now carry a typed link to their target plan, metric key, and signal type. The relationship appears in the work item API and audit snapshot, so teams can trace a follow-up back to the exact signal and measurement period.

An open or in-progress follow-up is unique per campaign, target plan, and metric. The API checks for an existing item while locking the target plan, and a partial unique index protects concurrent requests. Once a work item is completed or cancelled, a later actionable signal may create a new follow-up.
