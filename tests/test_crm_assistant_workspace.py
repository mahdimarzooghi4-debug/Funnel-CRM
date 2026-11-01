from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_assistant_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_assistant_workspace_has_evidence_question_summary_and_manager_signals() -> None:
    response = client().get("/workspace/crm-assistant")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-assistant-workspace.js"' in response.text
    assert 'id="question-form"' in response.text
    assert 'id="summary"' in response.text
    assert 'id="signals"' in response.text
    assert "پاسخ مدل زبانی تولید نمی‌کند" in response.text


def test_assistant_workspace_reads_scoped_report_and_renders_safe_evidence() -> None:
    response = client().get("/assets/crm-assistant-workspace.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/crm/analytics/marketing-manager/campaigns?" in response.text
    assert "manager_signals" in response.text
    assert "report_definition_version" in response.text
    assert "innerHTML" not in response.text
    assert "OpenAI" not in response.text
