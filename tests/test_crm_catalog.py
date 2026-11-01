from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from funnel_crm.api.v1.crm_catalog import router as catalog_router
from funnel_crm.platform.models import Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(catalog_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_catalog_items_and_immutable_price_versions_are_scoped_and_audited(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id, org_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(identity, AuthenticatedIdentity)
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        role = Role(tenant_id=tenant_id, name=f"Catalog manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=org_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.catalog:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.catalog:manage"),
        ])

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post("/api/v1/crm/catalog/items", headers=headers, json={
            "organization_unit_id": str(org_id), "code": " SKU-01 ",
            "name": "Service package", "item_type": "service", "category": "Marketing",
        })
        assert created.status_code == 201, created.text
        item = created.json()
        assert item["code"] == "SKU-01"
        assert item["version"] == 1
        assert item["category"] == "Marketing"
        search = await client.get("/api/v1/crm/catalog/items?search=service", headers=headers)
        assert [row["id"] for row in search.json()["items"]] == [item["id"]]
        category_filter = await client.get(
            "/api/v1/crm/catalog/items?category=Marketing", headers=headers,
        )
        assert [row["id"] for row in category_filter.json()["items"]] == [item["id"]]
        duplicate = await client.post("/api/v1/crm/catalog/items", headers=headers, json={
            "organization_unit_id": str(org_id), "code": "SKU-01",
            "name": "Duplicate", "item_type": "product",
        })
        assert duplicate.status_code == 409

        first_price = await client.post(
            f"/api/v1/crm/catalog/items/{item['id']}/prices", headers=headers,
            json={"amount": "1250.500000", "currency": "USD",
                  "effective_start": "2026-01-01", "effective_end": "2026-01-31"},
        )
        assert first_price.status_code == 201, first_price.text
        assert first_price.json()["version"] == 1
        invalid_price = await client.post(
            f"/api/v1/crm/catalog/items/{item['id']}/prices", headers=headers,
            json={"amount": "1400", "currency": "USD",
                  "effective_start": "2026-02-02", "effective_end": "2026-02-01"},
        )
        assert invalid_price.status_code == 422
        second_price = await client.post(
            f"/api/v1/crm/catalog/items/{item['id']}/prices", headers=headers,
            json={"amount": "1400", "currency": "USD",
                  "effective_start": "2026-02-01"},
        )
        assert second_price.status_code == 201, second_price.text
        assert second_price.json()["version"] == 2
        history = await client.get(f"/api/v1/crm/catalog/items/{item['id']}/prices", headers=headers)
        assert [row["version"] for row in history.json()["items"]] == [2, 1]
        assert history.json()["items"][0]["effective_end"] is None

        deactivated = await client.patch(
            f"/api/v1/crm/catalog/items/{item['id']}", headers=headers,
            json={"expected_version": 1, "is_active": False},
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["version"] == 2
        categorized = await client.patch(
            f"/api/v1/crm/catalog/items/{item['id']}", headers=headers,
            json={"expected_version": 2, "category": "Growth"},
        )
        assert categorized.status_code == 200
        assert categorized.json()["category"] == "Growth"
        assert categorized.json()["version"] == 3
        stale_item_update = await client.patch(
            f"/api/v1/crm/catalog/items/{item['id']}", headers=headers,
            json={"expected_version": 1, "name": "Stale edit"},
        )
        assert stale_item_update.status_code == 409
        blocked_price = await client.post(
            f"/api/v1/crm/catalog/items/{item['id']}/prices", headers=headers,
            json={"amount": "1500", "currency": "USD"},
        )
        assert blocked_price.status_code == 409
        active_items = await client.get("/api/v1/crm/catalog/items", headers=headers)
        all_items = await client.get("/api/v1/crm/catalog/items?active_only=false", headers=headers)
        assert active_items.json()["items"] == []
        assert len(all_items.json()["items"]) == 1
