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
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]
