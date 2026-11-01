from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_manager_workspace import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_marketing_manager_workspace_has_all_module_tabs_and_rtl_shell() -> None:
    response = make_client().get("/workspace/marketing-manager")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-manager-home.js"' in response.text
    assert 'id="module-data"' in response.text
    assert 'id="module-assistant"' in response.text
    for label in (
        "میزکار و داشبورد نقش‌محور",
        "تحقیق و شناخت بازار",
        "استراتژی و برنامه‌ریزی بازاریابی",
        "محصول، قیمت و پیشنهاد فروش",
        "کمپین و محتوا",
        "کانال‌ها و شرکای فروش",
        "مدیریت فروش و درآمد",
        "عملیات و منابع بازاریابی",
        "تحلیل و هوش تجاری",
        "دستیار هوشمند مدیر بازاریابی",
        "اتوماسیون و گردش‌کار",
        "چرخه عمر و تجربه مشتری",
        "یادگیری و بهبود مستمر",
        "شعب و بازاریابی محلی",
        "برند و اعتبار بازار",
        "مدیریت، امنیت و اتصال",
    ):
        assert label in response.text


def test_marketing_manager_client_connects_supported_tabs_to_workspace_scoped_apis() -> None:
    response = make_client().get("/assets/crm-manager-home.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert 'credentials: "same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/crm/analytics/marketing-manager/campaigns" in response.text
    assert "/api/v1/crm/campaigns?limit=8" in response.text
    assert "/api/v1/crm/segments?limit=8" in response.text
    assert "/api/v1/crm/marketing-calendar/events?period_start={start}&period_end={end}" in response.text
    assert "/api/v1/crm/analytics/customer-lifecycle/follow-up-candidates?inactive_for_days=30" in response.text
    assert "/api/v1/crm/work-items?organization_unit_id={organization_unit_id}" in response.text
    assert "/api/v1/crm/analytics/metrics?organization_unit_id={organization_unit_id}" in response.text
    assert "/api/v1/crm/marketing-assets?organization_unit_id={organization_unit_id}" in response.text
    assert "/api/v1/system/organization-units" in response.text
    assert "/api/v1/crm/opportunities?limit=8" in response.text
    assert "/api/v1/crm/marketing-learning/reviews" in response.text
    assert "/api/v1/integrations/connections" in response.text
    assert "async function askAssistant()" in response.text
    assert "report_definition_version" in response.text
    assert "innerHTML" not in response.text
