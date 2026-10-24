from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.budget_scenario_comparison import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_budget_comparison_workspace_serves_rtl_shell_with_security_headers() -> None:
    response = make_client().get("/workspace/budget-scenario-comparison")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/budget-scenario-comparison.js"' in response.text
    assert "فضای کاری" in response.text
    assert "گزارش واقعی؛ بدون پیش‌بینی" in response.text


def test_budget_comparison_workspace_client_uses_existing_authorized_read_apis() -> None:
    response = make_client().get("/assets/budget-scenario-comparison.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert 'credentials: "same-origin"' in response.text
    assert '"X-Workspace-ID": workspaceId' in response.text
    assert "/api/v1/crm/budget-scenarios" in response.text
    assert "/api/v1/crm/budget-scenarios/compare/performance-context?" in response.text
    assert "textContent" in response.text
    assert "innerHTML" not in response.text
