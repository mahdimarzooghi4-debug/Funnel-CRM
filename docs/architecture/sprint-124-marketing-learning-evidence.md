# Sprint 124: inspect evidence for evaluated marketing reviews

The marketing learning portfolio now lets a manager open an evaluated review and inspect its baseline and follow-up target values side by side. The view includes the recorded effectiveness assessment and lesson learned, and labels missing values as unrecorded.

The endpoint returns observed campaign measurements and the stored review. The interface states that an observed change alone does not establish causality. Access continues through the existing tenant-scoped review detail endpoint.

Validation covers the portfolio action, authenticated detail request, rendered follow-up measurement, and causal-language note. Local browser client, Python compilation, and diff checks pass; CI covers the database-backed API suite.
