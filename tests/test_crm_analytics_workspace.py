from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_analytics_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_analytics_workspace_has_campaign_activity_and_lifecycle_views() -> None:
    response = client().get("/workspace/crm-analytics")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-analytics-workspace.js"' in response.text
    assert 'id="campaign-table"' in response.text
    assert 'id="activity-summary"' in response.text
    assert 'id="lifecycle-stages"' in response.text


def test_analytics_workspace_uses_scoped_live_apis_and_safe_dom() -> None:
    response = client().get("/assets/crm-analytics-workspace.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/opportunity-organization-units" in response.text
    assert "/api/v1/crm/analytics/campaign-performance/portfolio" in response.text
    assert "/api/v1/crm/analytics/customer-activities/summary" in response.text
    assert "/api/v1/crm/analytics/customer-lifecycle?" in response.text
    assert "Promise.allSettled" in response.text
    assert "innerHTML" not in response.text
