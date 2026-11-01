# Sprint 226: Separate manager review before campaign activation

Scheduling and activation now require separate manager decisions:

- A draft campaign needs `proceed_to_schedule` before it can become scheduled.
- A scheduled campaign needs `proceed_to_launch` before it can become active.
- Each decision is recorded against the campaign's current status, update version, schedule, audience segment, channel, communication purpose, asset counts, and readiness check results.
- The transition is rejected if the latest decision is missing, has a different decision key, or its readiness basis no longer matches current data.

The existing campaign lifecycle state machine still controls the transitions. Activation only changes the CRM campaign status; it does not send messages or call a channel provider.
