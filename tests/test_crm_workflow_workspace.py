from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_workflow_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_workflow_workspace_has_review_rule_batch_action_and_queue() -> None:
    response = client().get("/workspace/crm-workflows")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-workflow-workspace.js"' in response.text
    assert 'id="inactive-days"' in response.text
    assert 'id="candidates"' in response.text
    assert 'id="workflow-form"' in response.text
    assert 'id="open-queue"' in response.text


def test_workflow_workspace_uses_reviewed_batch_api_and_safe_dom() -> None:
    response = client().get("/assets/crm-workflow-workspace.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/organization-units" in response.text
    assert "/api/v1/crm/analytics/customer-lifecycle/follow-up-candidates?" in response.text
    assert "/api/v1/crm/work-items/from-lifecycle-review" in response.text
    assert "/api/v1/crm/work-items?" in response.text
    assert "حداکثر ۵۰ پرونده" in response.text
    assert "innerHTML" not in response.text
    assert "interval" not in response.text.lower()
