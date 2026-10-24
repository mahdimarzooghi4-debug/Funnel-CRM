from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_budget_scenarios import router
from funnel_crm.platform.models import (
    CRMMarketingBudgetScenario,
    CRMMarketingBudgetScenarioLine,
    CRMMarketingCampaign,
    CRMProfileSegment,
    Role,
    RoleAssignment,
    RolePermission,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    identity: AuthenticatedIdentity,
) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_budget_scenarios_compare_and_replace_without_changing_campaign_budgets(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id = uuid4()
    campaigns = [
        CRMMarketingCampaign(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Email campaign", objective_key="retention",
            channel="email", planned_budget_amount=Decimal("1200.50"),
            planned_budget_currency="USD", starts_at=None, ends_at=None, status="draft",
        ),
        CRMMarketingCampaign(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Store campaign", objective_key="awareness",
            channel="store", planned_budget_amount=Decimal("300"),
            planned_budget_currency="EUR", starts_at=None, ends_at=None, status="draft",
        ),
    ]
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(
            CRMProfileSegment(
                id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
                name=f"Budget scenario audience {uuid4().hex[:8]}",
                criteria={"profile_kinds": ["person"]}, is_active=True,
            )
        )
        await context.session.flush()
        role = Role(tenant_id=tenant_id, name=f"Budget scenario manager {uuid4().hex[:8]}")
        context.session.add(role)
        context.session.add_all(campaigns)
        await context.session.flush()
        context.session.add_all(
            [
                RoleAssignment(
                    tenant_id=tenant_id,
                    membership_id=context.access.membership_id,
                    role_id=role.id,
                    organization_unit_id=root_id,
                ),
                *[
                    RolePermission(
                        tenant_id=tenant_id, role_id=role.id, permission_key=key
                    )
                    for key in (
                        "crm.campaign:view",
                        "crm.budget_scenario:view",
                        "crm.budget_scenario:manage",
                    )
                ],
            ]
        )
        await context.session.flush()
        campaign_ids = [campaign.id for campaign in campaigns]

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/v1/crm/budget-scenarios",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "Conservative",
                "allocations": [
                    {"campaign_id": str(campaign_ids[0]), "planned_budget_amount": "900", "planned_budget_currency": "USD"},
                    {"campaign_id": str(campaign_ids[1]), "planned_budget_amount": "250", "planned_budget_currency": "EUR"},
                ],
            },
        )
        assert first.status_code == 201, first.text
        second = await client.post(
            "/api/v1/crm/budget-scenarios",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "Growth",
                "allocations": [
                    {"campaign_id": str(campaign_ids[0]), "planned_budget_amount": "1500", "planned_budget_currency": "USD"},
                    {"campaign_id": str(campaign_ids[1]), "planned_budget_amount": "400", "planned_budget_currency": "EUR"},
                ],
            },
        )
        assert second.status_code == 201, second.text

        comparison = await client.get(
            "/api/v1/crm/budget-scenarios/compare",
            headers=headers,
            params={"scenario_ids": [first.json()["id"], second.json()["id"]]},
        )
        assert comparison.status_code == 200, comparison.text
        by_name = {item["name"]: item for item in comparison.json()["scenarios"]}
        assert by_name["Conservative"]["totals_by_currency"] == {
            "USD": "900.000000", "EUR": "250.000000"
        }
        assert by_name["Growth"]["totals_by_currency"] == {
            "USD": "1500.000000", "EUR": "400.000000"
        }

        replaced = await client.put(
            f"/api/v1/crm/budget-scenarios/{first.json()['id']}/allocations",
            headers=headers,
            json={
                "allocations": [
                    {"campaign_id": str(campaign_ids[0]), "planned_budget_amount": "800", "planned_budget_currency": "USD"},
                    {"campaign_id": str(campaign_ids[1]), "planned_budget_amount": "225", "planned_budget_currency": "EUR"},
                ]
            },
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["totals_by_currency"] == {
            "USD": "800.000000", "EUR": "225.000000"
        }

        mismatch = await client.post(
            "/api/v1/crm/budget-scenarios",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "Partial",
                "allocations": [
                    {"campaign_id": str(campaign_ids[0]), "planned_budget_amount": "500", "planned_budget_currency": "USD"}
                ],
            },
        )
        assert mismatch.status_code == 201, mismatch.text
        invalid_comparison = await client.get(
            "/api/v1/crm/budget-scenarios/compare",
            headers=headers,
            params={"scenario_ids": [first.json()["id"], mismatch.json()["id"]]},
        )
        assert invalid_comparison.status_code == 422

        archived = await client.post(
            f"/api/v1/crm/budget-scenarios/{first.json()['id']}/archive",
            headers=headers,
        )
        assert archived.status_code == 204
        cannot_edit = await client.put(
            f"/api/v1/crm/budget-scenarios/{first.json()['id']}/allocations",
            headers=headers,
            json={"allocations": []},
        )
        assert cannot_edit.status_code == 409

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        stored_campaigns = (
            await context.session.scalars(
                select(CRMMarketingCampaign).where(
                    CRMMarketingCampaign.tenant_id == tenant_id,
                    CRMMarketingCampaign.id.in_(campaign_ids),
                )
            )
        ).all()
        assert {
            campaign.id: (campaign.planned_budget_amount, campaign.planned_budget_currency)
            for campaign in stored_campaigns
        } == {
            campaigns[0].id: (Decimal("1200.50"), "USD"),
            campaigns[1].id: (Decimal("300"), "EUR"),
        }
        scenario = await context.session.scalar(
            select(CRMMarketingBudgetScenario).where(
                CRMMarketingBudgetScenario.tenant_id == tenant_id,
                CRMMarketingBudgetScenario.id == UUID(first.json()["id"]),
            )
        )
        assert scenario is not None
        assert scenario.status == "archived"
        count = await context.session.scalar(
            select(CRMMarketingBudgetScenarioLine.campaign_id).where(
                CRMMarketingBudgetScenarioLine.tenant_id == tenant_id,
                CRMMarketingBudgetScenarioLine.scenario_id == scenario.id,
            )
        )
        assert count is not None
