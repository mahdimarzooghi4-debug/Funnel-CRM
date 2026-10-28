# Sprint 203: record campaign experiment decisions

Managers can record one current decision on an experiment: adopt a specified variant, keep the control, retest, or stop. Each record includes a rationale and optional next action. Adopting requires a campaign that belongs to that experiment; other decisions cannot select a variant.

Decision changes require campaign management permission and generate an audit event with before and after state. The record remains separate from the descriptive readout and does not imply statistical confidence or causal proof.
