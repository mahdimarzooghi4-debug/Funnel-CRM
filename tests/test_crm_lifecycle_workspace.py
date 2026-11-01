from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_lifecycle_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_lifecycle_workspace_has_cohorts_activity_consent_and_followups() -> None:
    response = client().get("/workspace/crm-lifecycle")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-lifecycle-workspace.js"' in response.text
    assert 'id="cohorts"' in response.text
    assert 'id="channels"' in response.text
    assert 'id="profile-activities"' in response.text
    assert 'id="consents"' in response.text
    assert 'id="followups"' in response.text


def test_lifecycle_workspace_uses_scoped_read_apis_and_safe_dom() -> None:
    response = client().get("/assets/crm-lifecycle-workspace.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/organization-units" in response.text
    assert "/api/v1/crm/analytics/customer-lifecycle?" in response.text
    assert "/api/v1/crm/analytics/customer-activities/summary" in response.text
    assert "/api/v1/crm/analytics/customer-lifecycle/follow-up-candidates?" in response.text
    assert "/communication-consents?limit=20" in response.text
    assert "/activities?limit=10" in response.text
    assert "Promise.allSettled" in response.text
    assert "innerHTML" not in response.text
