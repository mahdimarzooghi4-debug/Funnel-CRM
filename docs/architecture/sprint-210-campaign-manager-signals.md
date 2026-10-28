# Sprint 210: Campaign manager signals

Campaign target performance analytics now includes transparent, rule-based manager signals. They flag incomplete measurement coverage before decisions and highlight metrics that missed targets when coverage is complete. Each signal includes the metric, actual and target values, coverage, priority, and a suggested review action.

These prompts are descriptive and do not establish causality, change campaign settings, or claim AI-generated recommendations. The API caps the signal list and reports when truncation occurs; no database migration is needed.
