from fastapi import FastAPI
from fastapi.testclient import TestClient
from funnel_crm.web.crm_channel_partners_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_channel_partners_page_and_security_headers() -> None:
    response = client().get("/workspace/crm-channel-partners")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-channel-partners.js"' in response.text


def test_channel_partners_script_uses_scoped_apis_and_safe_dom() -> None:
    response = client().get("/assets/crm-channel-partners.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/crm/analytics/campaign-performance/portfolio?" in response.text
    assert "/api/v1/crm/analytics/customer-activities/summary?" in response.text
    assert "/api/v1/crm/commission-plans" in response.text
    assert "innerHTML" not in response.text
