from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_commission_workspace import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_commission_workspace_is_rtl_data_free_shell_with_security_headers() -> None:
    response = make_client().get("/workspace/crm-commissions")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-commission-workspace.js"' in response.text
    assert "مدیریت پلن‌های کمیسیون فروش" in response.text
    assert "دستور پرداخت یا حقوق صادر نمی‌کند" in response.text


def test_commission_workspace_client_uses_authorized_apis_and_safe_dom_updates() -> None:
    response = make_client().get("/assets/crm-commission-workspace.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert 'credentials: "same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/commission-organization-units" in response.text
    assert "/api/v1/crm/commission-plans" in response.text
    assert "/versions" in response.text
    assert "/calculations" in response.text
    assert "sessionStorage" in response.text
    assert "innerHTML" not in response.text
