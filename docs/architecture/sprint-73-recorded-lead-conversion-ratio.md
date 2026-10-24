# Sprint 73: recorded conversions per recorded lead

Add a channel-level ratio of summed recorded conversions to summed recorded leads, compared between the equal-length reporting periods. Include only campaigns where both observations exist and the lead denominator is positive. Show the numerator, denominator, campaign count, and percentage-point change so the reader can see the evidence behind the ratio.

Describe the measure as recorded conversions per recorded lead; it does not establish unique-person conversion or attribution. Include the current value and period comparison context in CSV.

## Validation

Initial implementation commit `ba36b348fd5f9db44f62464d480328eff7e2cde2` passed GitHub Actions run `39969064986`: 94 Python tests passed (3 existing warnings), and the budget comparison browser behavior test passed.
