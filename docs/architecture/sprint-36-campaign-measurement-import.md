# Sprint 36: campaign measurement import

## Workflow

Managers can download the CSV header template, preview a file, and then import it in one atomic request. Preview parses and validates rows, reports row-level errors and shows how many dates would create or replace an observation. Invalid files cannot be applied.

CSV columns are `measured_on`, `source_label`, the supported count metrics, and optional paired amount/currency columns for actual spend and attributed revenue. Columns may be reordered; unknown and duplicate names are rejected. The file is limited to 1 MB and 366 daily rows. A campaign can appear in the import path only, never as a CSV-supplied ID.

## Safe replay and write behavior

The import request includes a caller idempotency key. The server hashes normalized rows and stores an import receipt. Repeating the same key and same content returns the original receipt without writing rows again; reusing the key for different content returns a conflict. Rows are upserted by campaign and measurement date, so corrected reports replace previous observations instead of double-counting.

Measurement changes, the batch receipt, and its audit event share the request transaction. The campaign's planned budget is not modified. Tenant RLS and campaign manage permission apply to preview and import; the static template requires campaign view permission.
