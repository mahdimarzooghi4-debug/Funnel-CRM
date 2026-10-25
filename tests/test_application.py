from fastapi.testclient import TestClient

from funnel_crm.main import app

client = TestClient(app)


def test_liveness_endpoint() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint() -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_versioned_system_route() -> None:
    response = client.get("/api/v1/system")

    assert response.status_code == 200
    assert response.json() == {"service": "funnel-crm", "api_version": "v1"}


def test_openapi_exposes_versioned_route_and_operations() -> None:
    schema = client.get("/openapi.json").json()

    assert schema["info"]["title"] == "Funnel CRM API"
    assert schema["info"]["version"] == "0.1.0"
    assert "/api/v1/system" in schema["paths"]
    assert "/api/v1/crm/catalog/items" in schema["paths"]
    assert "/api/v1/crm/opportunities/{opportunity_id}/catalog-items" in schema["paths"]
    assert "/api/v1/crm/opportunities/{opportunity_id}/offer-drafts" in schema["paths"]
    assert "/api/v1/crm/opportunities/{opportunity_id}/offer-drafts/{offer_id}/revisions" in schema["paths"]
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]


def test_budget_scenario_comparison_workspace_is_mounted() -> None:
    response = client.get("/workspace/budget-scenario-comparison")

    assert response.status_code == 200
    assert "مقایسهٔ سناریوهای بودجه" in response.text


def test_commission_workspace_is_mounted() -> None:
    response = client.get("/workspace/crm-commissions")

    assert response.status_code == 200
    assert "مدیریت پلن‌های کمیسیون فروش" in response.text


def test_catalog_workspace_is_mounted_with_security_headers() -> None:
    response = client.get("/workspace/crm-catalog")

    assert response.status_code == 200
    assert "کاتالوگ محصول و خدمت" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_catalog_workspace_script_is_mounted() -> None:
    response = client.get("/assets/crm-catalog-workspace.js")

    assert response.status_code == 200
    assert "X-Workspace-ID" in response.text
    assert "replaceChildren" in response.text
    assert "innerHTML" not in response.text
    page = client.get("/workspace/crm-catalog")
    assert "item-category" in page.text
    assert "item-search" in page.text


def test_offer_workspace_is_mounted_with_safe_api_client() -> None:
    page = client.get("/workspace/crm-offers")
    script = client.get("/assets/crm-offer-workspace.js")
    assert page.status_code == script.status_code == 200
    assert 'lang="fa" dir="rtl"' in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "پیش‌نویس پیشنهاد فروش" in page.text
    assert "/api/v1/system/opportunity-organization-units" in script.text
    assert "/offer-drafts" in script.text
    assert "ساخت نسخهٔ اصلاح‌شده" in script.text
    assert "credentials:" in script.text and '"same-origin"' in script.text
    assert "X-Workspace-ID" in script.text
    assert "innerHTML" not in script.text
