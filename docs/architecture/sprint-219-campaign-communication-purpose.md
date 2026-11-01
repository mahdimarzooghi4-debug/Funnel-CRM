# Sprint 219: Campaign communication purpose

Every campaign now stores a stable communication purpose key, defaulting to `marketing` for existing and newly created plans unless the caller specifies another valid key. Draft campaigns may update the purpose with their other planning fields.

Campaign readiness uses the stored purpose rather than accepting a per-request override, and returns the purpose being evaluated. The database migration backfills existing campaigns with `marketing`; the key is constrained to the same lowercase identifier format as consent events.
