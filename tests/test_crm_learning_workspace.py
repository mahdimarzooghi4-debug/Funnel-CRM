from fastapi import FastAPI
from fastapi.testclient import TestClient

from funnel_crm.web.crm_learning_workspace import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_learning_workspace_has_experiments_reviews_and_evaluation() -> None:
    response = client().get("/workspace/crm-learning")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'lang="fa" dir="rtl"' in response.text
    assert 'src="/assets/crm-learning-workspace.js"' in response.text
    assert 'id="experiment-form"' in response.text
    assert 'id="review-form"' in response.text
    assert 'id="evaluation-form"' in response.text
    assert 'id="readout"' in response.text


def test_learning_workspace_uses_scoped_learning_and_experiment_apis_safely() -> None:
    response = client().get("/assets/crm-learning-workspace.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'credentials:"same-origin"' in response.text
    assert '"X-Workspace-ID"' in response.text
    assert "/api/v1/system/workspaces" in response.text
    assert "/api/v1/system/organization-units" in response.text
    assert "/api/v1/crm/campaign-experiments" in response.text
    assert "/api/v1/crm/marketing-learning/reviews/portfolio?" in response.text
    assert "/api/v1/crm/marketing-learning/reviews/" in response.text
    assert "/api/v1/crm/campaigns/" in response.text
    assert 'method:"PATCH"' in response.text
    assert 'method:"POST"' in response.text
    assert "علیت" in response.text
    assert "innerHTML" not in response.text
