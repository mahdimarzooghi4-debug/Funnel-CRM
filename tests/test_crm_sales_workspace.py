from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_sales_workspace import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_sales_workspace_has_pipeline_followup_forecast_and_targets_views() -> None:
    response = make_client().get("/workspace/crm-sales")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-sales-workspace.js"' in response.text
    assert 'id="view-pipeline"' in response.text
    assert 'id="view-followups"' in response.text
    assert 'id="view-forecast"' in response.text
    assert 'id="view-targets"' in response.text
    assert "مدیریت فروش و درآمد" in response.text


def test_sales_workspace_client_uses_scoped_sales_apis_and_safe_dom() -> None:
    response = make_client().get("/assets/crm-sales-workspace.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/opportunity-organization-units" in response.text
    assert "/api/v1/crm/opportunities/pipelines" in response.text
    assert "/api/v1/crm/opportunities?pipeline_id=" in response.text
    assert "/api/v1/crm/opportunities/worklist" in response.text
    assert "/api/v1/crm/sales-forecast/opportunities" in response.text
    assert "/api/v1/crm/sales-targets" in response.text
    assert 'method:"PATCH"' in response.text
    assert 'method:"POST"' in response.text
    assert "innerHTML" not in response.text
