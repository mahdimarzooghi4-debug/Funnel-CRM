# Sprint 65: reproducible budget report links

After a successful comparison, update the current page URL with the authorized workspace, organization unit, reporting period, and selected scenario IDs. Opening a valid report link reloads the authorized choices and reruns the comparison. The link identifies a live query; it is not an immutable historical snapshot, and current permissions are checked again by the existing APIs.

The browser test verifies both deep-link restoration and URL generation, including repeated scenario parameters and preserved page fragment.

## Validation

Pending exact-head CI.
