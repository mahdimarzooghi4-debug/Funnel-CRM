from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from funnel_crm.api.v1.crm_opportunities import router as opportunities_router
from funnel_crm.api.v1.crm_sales_forecasting import router as forecasting_router
from funnel_crm.api.v1.crm_sales_targets import router as sales_targets_router
from funnel_crm.platform.models import CRMOpportunity, Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(opportunities_router, prefix="/api/v1")
    app.include_router(forecasting_router, prefix="/api/v1")
    app.include_router(sales_targets_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_target_forecast_alignment_uses_probability_and_separates_currencies(
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
        role = Role(tenant_id=tenant_id, name=f"Target forecast manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        permissions = (
            "crm.pipeline:manage",
            "crm.opportunity:view",
            "crm.sales_target:view",
            "crm.sales_target:manage",
        )
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
                for permission in permissions
            ],
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    period_start = date.today()
    period_end = period_start + timedelta(days=30)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        pipeline_response = await client.post(
            "/api/v1/crm/opportunities/pipelines",
            headers=headers,
            json={
                "pipeline_key": f"alignment-{uuid4().hex[:8]}",
                "display_name": "Alignment pipeline",
                "is_default": True,
                "stages": [
                    {"key": "proposal", "name": "Proposal", "position": 1},
                    {"key": "won", "name": "Won", "position": 2, "outcome_key": "won"},
                    {"key": "lost", "name": "Lost", "position": 3, "outcome_key": "lost"},
                ],
            },
        )
        assert pipeline_response.status_code == 201, pipeline_response.text
        pipeline_id = UUID(pipeline_response.json()["id"])

        probability = await client.patch(
            f"/api/v1/crm/sales-forecast/pipelines/{pipeline_id}/stages/proposal/probability",
            headers=headers,
            json={"probability_percent": 50},
        )
        assert probability.status_code == 200, probability.text

        target_ids = {}
        for currency, amount in (("USD", "1000"), ("EUR", "2000")):
            target_response = await client.post(
                "/api/v1/crm/sales-targets",
                headers=headers,
                json={
                    "organization_unit_id": str(root_id),
                    "pipeline_id": str(pipeline_id),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "currency": currency,
                    "target_amount": amount,
                },
            )
            assert target_response.status_code == 201, target_response.text
            target_ids[currency] = target_response.json()["id"]

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add_all([
            CRMOpportunity(
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                profile_id=None,
                pipeline_id=pipeline_id,
                name="Recorded won deal",
                stage_key="won",
                amount=Decimal("100"),
                currency="USD",
                expected_close_date=period_start,
            ),
            CRMOpportunity(
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                profile_id=None,
                pipeline_id=pipeline_id,
                name="USD proposal",
                stage_key="proposal",
                amount=Decimal("500"),
                currency="USD",
                expected_close_date=period_start + timedelta(days=5),
            ),
            CRMOpportunity(
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                profile_id=None,
                pipeline_id=pipeline_id,
                name="EUR proposal",
                stage_key="proposal",
                amount=Decimal("1000"),
                currency="EUR",
                expected_close_date=period_start + timedelta(days=5),
            ),
        ])
        await context.session.flush()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/sales-targets/forecast-alignment",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
    assert response.status_code == 200, response.text
    rows = {row["currency"]: row for row in response.json()["items"]}
    assert rows["USD"]["won_amount"] == "100.000000"
    assert rows["USD"]["weighted_open_pipeline_amount"] == "250.00"
    assert rows["USD"]["expected_period_amount"] == "350.00"
    assert rows["USD"]["target_gap_amount"] == "650.00"
    assert rows["USD"]["outlook"] == "forecast_below_target"
    assert rows["EUR"]["weighted_open_pipeline_amount"] == "500.00"
    assert rows["EUR"]["expected_period_amount"] == "500.00"
