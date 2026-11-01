from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_operations_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_operations_workspace_exposes_queue_resource_summary_and_create_form() -> None:
    response = client().get("/workspace/crm-operations")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-operations-workspace.js"' in response.text
    assert 'id="queue"' in response.text
    assert 'id="kpi-overdue"' in response.text
    assert 'id="kpi-unassigned"' in response.text
    assert 'id="task-form"' in response.text


def test_operations_workspace_client_uses_scoped_work_item_apis_and_safe_dom() -> None:
    response = client().get("/assets/crm-operations-workspace.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/opportunity-organization-units" in response.text
    assert "/api/v1/crm/profiles?limit=200" in response.text
    assert "/api/v1/crm/work-items?" in response.text
    assert 'method:"PATCH"' in response.text
    assert 'method:"POST"' in response.text
    assert "innerHTML" not in response.text
