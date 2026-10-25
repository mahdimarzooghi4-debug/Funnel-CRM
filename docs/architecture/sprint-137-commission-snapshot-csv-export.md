# Sprint 137: Commission snapshot CSV export

An authorized user can download a saved commission calculation as CSV. Export access requires both `crm.commission:view` and the separate `crm.commission:export` permission in the plan's organization scope. The file contains the immutable snapshot values, plan version, period, currency totals, seller membership identifiers, and source event identifiers; it does not recalculate from current commerce events.

Each export is audited, returned with no-store headers, and available from calculation history in the manager workspace. CSV cells derived from source identifiers are escaped against spreadsheet formula execution.

Validation covers the export permission boundary, snapshot/source lineage, response headers, and the workspace download action. PostgreSQL CI applies the permission migration and runs the full integration suite.
