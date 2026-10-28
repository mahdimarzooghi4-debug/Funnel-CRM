# Sprint 209: Campaign lifecycle

Campaigns move through draft, scheduled, active, paused, completed, and archived states. The API validates each transition and audits previous and next status. Scheduling requires dates, an active audience segment, an approved content asset, and no assets waiting for review or revision. Transitions require campaign management permission and use a row lock.

The marketing calendar includes all non-archived campaigns. Migration downgrade maps scheduled, active, and paused to draft, and completed to archived.
