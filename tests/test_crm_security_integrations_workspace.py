from fastapi import FastAPI
from fastapi.testclient import TestClient
from funnel_crm.web.crm_security_integrations_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_security_integrations_workspace_page_and_security_headers() -> None:
    response = client().get("/workspace/crm-security-integrations")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-security-integrations.js"' in response.text
    assert "اعتبارنامهٔ محصول فقط هنگام ایجاد یا چرخش نمایش داده می‌شود" in response.text


def test_security_integrations_script_uses_admin_apis_without_rendering_payloads() -> None:
    response = client().get("/assets/crm-security-integrations.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert "/api/v1/integrations/connections/consent-sync" in response.text
    assert "/api/v1/integrations/events/health" in response.text
    assert "/api/v1/integrations/events/failed?limit=50" in response.text
    assert "/rotate-credential" in response.text
    assert "/retry" in response.text
    assert "innerHTML" not in response.text
