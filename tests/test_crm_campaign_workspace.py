from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_campaign_workspace import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_campaign_workspace_has_campaign_content_and_calendar_views() -> None:
    response = make_client().get("/workspace/crm-campaigns")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-campaign-workspace.js"' in response.text
    assert 'id="view-campaigns"' in response.text
    assert 'id="view-assets"' in response.text
    assert 'id="view-calendar"' in response.text
    assert "مدیریت کمپین و محتوا" in response.text


def test_campaign_workspace_client_uses_scoped_campaign_asset_and_calendar_apis() -> None:
    response = make_client().get("/assets/crm-campaign-workspace.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/organization-units" in response.text
    assert "/api/v1/crm/segments?limit=100" in response.text
    assert "/api/v1/crm/campaigns" in response.text
    assert "/api/v1/crm/marketing-assets" in response.text
    assert "/submit" in response.text
    assert "/review" in response.text
    assert "/api/v1/crm/marketing-calendar/events" in response.text
    assert 'method:"PATCH"' in response.text
    assert 'method:"POST"' in response.text
    assert "innerHTML" not in response.text
