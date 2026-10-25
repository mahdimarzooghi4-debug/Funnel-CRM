from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_activity_capture import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_activity_capture_page_is_rtl_and_has_strict_shell_headers() -> None:
    response = make_client().get("/workspace/crm-activity-capture")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-activity-capture.js"' in response.text
    assert "شناسهٔ فضای کاری" in response.text
    assert "شناسهٔ پروفایل CRM" in response.text
    assert "صف همگام‌سازی" in response.text


def test_activity_capture_client_uses_local_queue_and_authorized_sync_contract() -> None:
    response = make_client().get("/assets/crm-activity-capture.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert 'window.indexedDB.open(DB_NAME, 1)' in response.text
    assert '"X-Workspace-ID": item.workspace_id' in response.text
    assert 'credentials: "same-origin"' in response.text
    assert "/activities/sync" in response.text
    assert "source_event_id: item.source_event_id" in response.text
    assert "needs_attention" in response.text
    assert "innerHTML" not in response.text


def test_budget_workspace_links_to_field_activity_capture() -> None:
    from funnel_crm.web.budget_scenario_comparison import _PAGE

    assert 'href="/workspace/crm-activity-capture"' in _PAGE
