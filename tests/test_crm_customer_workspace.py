from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_customer_workspace import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_customer_workspace_has_rtl_profile_list_and_detail_sections() -> None:
    response = make_client().get("/workspace/crm-customers")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-customer-workspace.js"' in response.text
    assert 'id="organization-unit"' in response.text
    assert 'id="create-form"' in response.text
    assert 'id="edit-form"' in response.text
    assert "مشتریان و پرونده‌ها" in response.text
    assert "راه‌های ارتباطی" in response.text
    assert "تاریخچهٔ تعامل" in response.text
    assert "رضایت ارتباطی" in response.text


def test_customer_workspace_client_uses_scoped_profile_and_contact_apis_safely() -> None:
    response = make_client().get("/assets/crm-customer-workspace.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert 'credentials: "same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/organization-units" in response.text
    assert "/api/v1/crm/profiles" in response.text
    assert "/contact-points" in response.text
    assert "/activities?limit=50" in response.text
    assert "/communication-consents?limit=100" in response.text
    assert 'method:"PATCH"' in response.text
    assert 'method:"POST"' in response.text
    assert "innerHTML" not in response.text
