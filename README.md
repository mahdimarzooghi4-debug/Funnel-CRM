# Funnel CRM

The repository contains the technical design and executable service foundation for the Funnel CRM platform.

## Run locally

Requires Python 3.12 or later and PostgreSQL 16.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/funnel_crm
export TEST_DATABASE_URL="$DATABASE_URL"
alembic upgrade head
uvicorn funnel_crm.main:app --reload
```

The service provides:

- `GET /healthz` for process liveness
- `GET /readyz` for application readiness
- Versioned API routes under `/api/v1`
- OpenAPI schema at `/openapi.json` and interactive documentation at `/docs`

The platform model provisions each workspace with its own root organization. Composite foreign keys prevent organization-parent and workspace-root references from crossing tenant boundaries. PostgreSQL integration tests run against the versioned schema.

Readiness currently confirms application initialization. Infrastructure health checks will be added with the corresponding service integration.


## Product event worker

Run event consumers in a dedicated worker process, separate from HTTP request handling:

```sh
python -m funnel_crm.platform.product_event_worker
```

Configure `DATABASE_URL`, `FUNNEL_CRM_INTEGRATION_PAYLOAD_KEYRING`, and `FUNNEL_CRM_CONTACT_KEYRING`. The worker polls every 5 seconds by default; `FUNNEL_CRM_EVENT_WORKER_POLL_SECONDS` can be set from 0.25 to 300. Workspace batches run concurrently with a default bound of 4; `FUNNEL_CRM_EVENT_WORKER_TENANT_CONCURRENCY` accepts 1 to 32. `FUNNEL_CRM_EVENT_WORKER_ONCE=true` runs one polling cycle for controlled jobs.

On SIGTERM or SIGINT, the worker finishes the current polling cycle, then stops before claiming another batch. The worker processes customer profile/activity events, the identity-mapped `crm.commerce.order` contract, the existing CRM-ID-based `commerce.order` contract for paid/refunded commerce facts, and product-reported consent changes via `crm.customer.communication_consent` v1. Consent events require a tenant-scoped customer identity mapping and retain product/event provenance; replayed source events are idempotent. Products with the `crm.customer.communication_eligibility` v1 grant can read a live, fail-closed eligibility result before communication, individually or in batches of up to 100 checks. Products with the separate `crm.customer.communication_consent_changes` v1 grant can page through a durable, ordered consent change feed using a product-specific cursor. They acknowledge each processed page through the same API contract; acknowledgements are monotonic and bounded by the produced cursor. A status endpoint reports produced and acknowledged cursors and the number of pending changes. It discovers workspace UUIDs from a read-only operational registry populated automatically when a workspace is created. The registry contains no customer or event data; each inbox claim and consumer still runs with the selected tenant set in the RLS context. Do not expose keyring values in logs.
