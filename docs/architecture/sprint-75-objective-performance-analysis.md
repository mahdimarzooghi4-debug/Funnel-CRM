# Sprint 75: marketing objective performance comparison

Add a cross-period comparison grouped by each campaign's configured marketing objective and channel. Summarize observed leads and conversions separately, preserve observed zeroes, and show how many campaigns contributed to each value relative to the group's campaign count.

This is a descriptive view of recorded counts; it does not infer attribution or cause. Include the current count, previous count, change, and evidence coverage in CSV exports.

## Validation

Initial implementation commit `3ea60f09d0c1bb968e88c49f2aa501c8024c583e` exposed missing objective keys in a browser-test fixture. After completing the fixture, commit `f3cb996762e2143e4b0ac074dfb777cdf6dd89d8` passed GitHub Actions run `39971075381`: 94 Python tests passed (3 existing warnings), and the browser behavior test passed.
