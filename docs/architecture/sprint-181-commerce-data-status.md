# Sprint 181: commerce data status

Campaign decision queue items now distinguish three states: linked commerce events were observed, no linked event exists in the campaign period, or the viewer lacks permission to see commerce data. An empty outcome list no longer has to stand in for all three situations.

The status exposes no commerce values when access is missing. Regression coverage checks all three states.
