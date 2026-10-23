# Sprint 63: channel-level evidence coverage

Add a channel-level breakdown of campaign evidence to the budget comparison report. For each recorded channel, show campaign count and the number of campaigns with spend, lead, and conversion data. Keep currencies separate: this view counts campaigns with recorded evidence and does not total money across or within channels.

Campaigns without a usable channel value appear under an explicit unassigned label. Channel names use text-only DOM rendering. The CSV includes the same counts.

## Validation

Exact head `4e9f229613096aefabc9b63852cacad0297e8c6c`: GitHub Actions run `39955154443` succeeded; Alembic passed, pytest reported 94 passed with 3 warnings, and the Node client behavior test passed.
