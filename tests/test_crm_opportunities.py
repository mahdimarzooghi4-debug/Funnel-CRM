from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from funnel_crm.api.v1.crm_opportunities import router
from funnel_crm.platform.models import Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_sales_pipeline_and_opportunity_board_are_scoped_and_audited(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        role = Role(tenant_id=tenant_id, name=f"Opportunity manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id,
                membership_id=context.access.membership_id,
                role_id=role.id,
                organization_unit_id=root_id,
            ),
            *[
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key=permission,
                )
                for permission in (
                    "crm.pipeline:manage",
                    "crm.opportunity:view",
                    "crm.opportunity:create",
                    "crm.opportunity:update",
                )
            ],
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        pipeline = await client.post(
            "/api/v1/crm/opportunities/pipelines",
            headers=headers,
            json={
                "pipeline_key": f"retail-{uuid4().hex[:6]}",
                "display_name": "Retail sales",
                "is_default": True,
                "stages": [
                    {"key": "qualified", "name": "Qualified", "position": 1},
                    {"key": "proposal", "name": "Proposal", "position": 2},
                ],
            },
        )
        assert pipeline.status_code == 201, pipeline.text
        pipeline_id = pipeline.json()["id"]

        created = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Central store rollout",
                "stage_key": "qualified",
                "amount": "12500.00",
                "currency": "USD",
                "expected_close_date": "2026-12-01",
            },
        )
        assert created.status_code == 201, created.text
        opportunity_id = created.json()["id"]

        board = await client.get(
            "/api/v1/crm/opportunities",
            headers=headers,
            params={"stage_key": "qualified"},
        )
        assert board.status_code == 200, board.text
        assert board.json()["total"] == 1
        assert board.json()["items"][0]["id"] == opportunity_id

        moved = await client.patch(
            f"/api/v1/crm/opportunities/{opportunity_id}",
            headers=headers,
            json={"stage_key": "proposal", "amount": "13250.00", "currency": "USD"},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["stage_key"] == "proposal"
        assert moved.json()["amount"] == "13250.00"

        invalid_stage = await client.patch(
            f"/api/v1/crm/opportunities/{opportunity_id}",
            headers=headers,
            json={"stage_key": "not-a-stage"},
        )
        assert invalid_stage.status_code == 422

        invalid_money = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Incomplete amount",
                "stage_key": "qualified",
                "amount": "20",
            },
        )
        assert invalid_money.status_code == 422
