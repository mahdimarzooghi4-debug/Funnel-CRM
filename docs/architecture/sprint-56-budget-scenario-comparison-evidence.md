# Sprint 56: compare budget scenarios with recorded evidence

A new read-only comparison endpoint places multiple budget allocations beside recorded results for the same campaign set and a selected period.

- Scenario allocations remain distinct from observed spend and outcomes.
- Reconciliation reports the planned amount, comparable planned amount, same-currency recorded spend, observed variance, and the number of allocations with or without compatible spend.
- Currency mismatches stay visible in the campaign's recorded-spend breakdown and are never converted into the scenario currency.
- Leads and conversions include recorded-day coverage; the response explicitly marks counterfactual outcomes as not predicted.
- The comparison requires budget-scenario and campaign view permissions and is audited.
