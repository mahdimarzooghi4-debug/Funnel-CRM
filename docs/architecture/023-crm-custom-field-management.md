# CRM custom field management and required values

- Sprint: 16
- API: workspace-level custom field definitions and profile creation validation
- Related: CRM-DOM-01 and CRM-DOM-02

## Management

A member with `crm.custom_field:manage` at the Workspace root can list, create, update, and deactivate definitions. Entity kind and field key are immutable; definitions are deactivated rather than deleted. Choice options cannot be removed while stored values use them. A field cannot become required until every existing profile of that kind has a value.

Definition edits remain tenant-scoped and pass through the existing database audit trigger. Customer-entered field values are never included in definition or profile audit snapshots.

## Profile creation

`POST /api/v1/crm/profiles` accepts an optional `custom_fields` object keyed by field key. The API validates the full input before writing: unknown or inactive keys are rejected, scalar values must match their active definition, and every active required field for the profile kind must be present. The profile, tenant record, and custom values are written in one transaction.

Existing per-profile custom field read and update routes remain available. Required-field enforcement is server-side and cannot be bypassed by omitting form validation in a client.

## Access

Definition management uses workspace-root scope because definitions apply across the workspace. Profile creation still requires `crm.profile:create` at the requested organization unit. Tenant RLS and same-tenant foreign keys remain the database boundary.
