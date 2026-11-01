# Sprint 190: latest measurement date

Each campaign decision-queue item exposes the most recent `measured_on` date among its campaign measurements inside the target plan period. The field is `null` when no measurement is recorded.

The queue reports the date without classifying it as fresh or stale, since no freshness threshold is configured.
