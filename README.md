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
