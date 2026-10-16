# Funnel CRM

The repository contains the technical design and the first executable service foundation for the Funnel CRM platform.

## Run locally

Requires Python 3.12 or later.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn funnel_crm.main:app --reload
```

The service provides:

- `GET /healthz` for process liveness
- `GET /readyz` for application readiness
- Versioned API routes under `/api/v1`
- OpenAPI schema at `/openapi.json` and interactive documentation at `/docs`

Readiness currently confirms application initialization. Checks for required infrastructure will be added with those dependencies.
