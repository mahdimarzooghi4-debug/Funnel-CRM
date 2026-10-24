# Sprint 87: support conversations and SLA reporting

Expand the customer support module with an append-only case timeline, internal notes, and staff-recorded response entries. Recording a response is an explicit CRM action that captures the first-response timestamp; this API does not transmit messages to customers or claim delivery through an external channel.

Add a tenant- and organization-scoped SLA report for cases created in a selected date period. It counts cases with a response deadline, first responses recorded, on-time and late responses, active overdue cases, and cases still awaiting a response. The on-time rate uses only cases with both a configured response deadline and a recorded first response as its denominator; missing deadlines and pending responses remain visible separately. Response deadlines remain manager-entered and are not inferred from a business-hours calendar.
