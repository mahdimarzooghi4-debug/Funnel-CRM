"""FastAPI application entry point."""

from fastapi import FastAPI

from funnel_crm.api.v1.router import router as v1_router
from funnel_crm.web.budget_scenario_comparison import router as budget_scenario_workspace_router
from funnel_crm.web.crm_activity_capture import router as crm_activity_capture_router

app = FastAPI(
    title="Funnel CRM API",
    summary="Versioned API for the Funnel CRM platform.",
    version="0.1.0",
    description=(
        "The CRM backend is organized as a modular service. "
        "Public business endpoints are grouped under the versioned /api/v1 prefix."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/healthz", tags=["operations"], operation_id="getLiveness")
async def liveness() -> dict[str, str]:
    """Report that the HTTP process is alive."""
    return {"status": "ok"}


@app.get("/readyz", tags=["operations"], operation_id="getReadiness")
async def readiness() -> dict[str, str]:
    """Report that the application has initialized and can accept requests.

    Dependency-specific readiness checks will be added with the database and
    other required infrastructure. Liveness deliberately remains independent.
    """
    return {"status": "ready"}


app.include_router(v1_router)
app.include_router(budget_scenario_workspace_router)
app.include_router(crm_activity_capture_router)
