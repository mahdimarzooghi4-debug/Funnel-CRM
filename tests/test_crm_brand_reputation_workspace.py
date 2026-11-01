from fastapi import FastAPI
from fastapi.testclient import TestClient
from funnel_crm.web.crm_brand_reputation_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_brand_reputation_workspace_page_and_security_headers() -> None:
    response = client().get("/workspace/crm-brand-reputation")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-brand-reputation.js"' in response.text
    assert "پروندهٔ پشتیبانی معادل شکایت یا رضایت‌سنجی نیست" in response.text


def test_brand_reputation_script_uses_scoped_crm_apis_and_safe_dom() -> None:
    response = client().get("/assets/crm-brand-reputation.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/crm/support-cases?organization_unit_id=" in response.text
    assert "/api/v1/crm/analytics/customer-activities/summary?" in response.text
    assert "innerHTML" not in response.text
