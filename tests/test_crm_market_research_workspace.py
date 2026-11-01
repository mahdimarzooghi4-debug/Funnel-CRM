from fastapi import FastAPI
from fastapi.testclient import TestClient
from funnel_crm.web.crm_market_research_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_market_research_workspace_page_and_security_headers() -> None:
    response = client().get("/workspace/crm-market-research")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-market-research.js"' in response.text
    assert 'id="segment-form"' in response.text


def test_market_research_script_uses_scoped_apis_and_safe_dom() -> None:
    response = client().get("/assets/crm-market-research.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' not in response.text
    assert "/api/v1/crm/segments" in response.text
    assert "/api/v1/crm/analytics/customer-activities/summary?" in response.text
    assert "/preview?limit=10" in response.text
    assert "innerHTML" not in response.text
