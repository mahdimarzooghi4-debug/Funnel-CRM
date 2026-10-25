from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_budget_scenarios import router
from funnel_crm.api.v1.crm_workspace_context import router as workspace_context_router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingBudgetScenario,
    CRMMarketingBudgetScenarioLine,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
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
    app.include_router(workspace_context_router, prefix="/api/v1")
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
                CRMMarketingCampaignMeasurement(
                    id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                    campaign_id=campaigns[0].id, measured_on=date(2026, 10, 2),
                    source_label="budget-scenario-comparison-email", leads=12, conversions=3,
                    actual_spend_amount=Decimal("200"), actual_spend_currency="USD",
                ),
                CRMMarketingCampaignMeasurement(
                    id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                    campaign_id=campaigns[1].id, measured_on=date(2026, 10, 2),
                    source_label="budget-scenario-comparison-store", leads=6, conversions=1,
                    actual_spend_amount=Decimal("30"), actual_spend_currency="USD",
                ),
            ]
        )
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
        workspace_response = await client.get("/api/v1/system/workspaces")
        assert workspace_response.status_code == 200, workspace_response.text
        workspace_choices = workspace_response.json()
        assert len(workspace_choices) == 1
        assert workspace_choices[0]["id"] == str(tenant_id)
        assert workspace_choices[0]["name"] == "Tenant A"
        assert workspace_choices[0]["root_organization_id"] == str(root_id)
        assert UUID(workspace_choices[0]["membership_id"])

        organization_response = await client.get(
            "/api/v1/system/organization-units", headers=headers
        )
        assert organization_response.status_code == 200, organization_response.text
        assert [unit["id"] for unit in organization_response.json()] == [str(root_id)]

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

        scenario_list = await client.get(
            "/api/v1/crm/budget-scenarios",
            headers=headers,
            params={"organization_unit_id": str(root_id), "status": "draft"},
        )
        assert scenario_list.status_code == 200, scenario_list.text
        assert {item["name"] for item in scenario_list.json()} == {"Conservative", "Growth"}

        comparison = await client.get(
            "/api/v1/crm/budget-scenarios/compare",
            headers=headers,
            params={"scenario_ids": [first.json()["id"], second.json()["id"]]},
        )
        assert comparison.status_code == 200, comparison.text
        by_name = {item["name"]: item for item in comparison.json()["scenarios"]}

        evidence_comparison = await client.get(
            "/api/v1/crm/budget-scenarios/compare/performance-context",
            headers=headers,
            params={
                "scenario_ids": [first.json()["id"], second.json()["id"]],
                "period_start": "2026-10-01",
                "period_end": "2026-10-03",
            },
        )
        assert evidence_comparison.status_code == 200, evidence_comparison.text
        evidence = evidence_comparison.json()
        assert evidence["period_calendar_days"] == 3
        assert evidence["currency_conversion_applied"] is False
        assert evidence["causal_attribution_applied"] is False
        assert evidence["counterfactual_outcomes_predicted"] is False
        summaries = {item["name"]: item for item in evidence["scenarios"]}
        conservative_usd = summaries["Conservative"]["reconciliation_by_currency"]["USD"]
        growth_usd = summaries["Growth"]["reconciliation_by_currency"]["USD"]
        assert conservative_usd["comparable_planned_amount"] == "900.000000"
        assert conservative_usd["observed_spend_amount"] == "200.000000"
        assert conservative_usd["variance_amount"] == "700.000000"
        assert growth_usd["variance_amount"] == "1300.000000"
        conservative_eur = summaries["Conservative"]["reconciliation_by_currency"]["EUR"]
        assert conservative_eur["observed_spend_amount"] is None
        assert conservative_eur["currency_mismatch_allocation_count"] == 1
        campaign_evidence = {item["campaign_name"]: item for item in evidence["campaigns"]}
        assert campaign_evidence["Email campaign"]["metrics"]["leads"]["actual"] == 12
        store = campaign_evidence["Store campaign"]
        assert store["recorded_spend_by_currency"] == {"USD": "30.000000"}
        assert store["scenario_allocations"][0]["actual_spend_in_allocation_currency"] is None
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


@pytest.mark.asyncio
async def test_budget_scenario_performance_context_uses_matching_currency_and_shows_coverage(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id, campaign_usd_id, campaign_eur_id, scenario_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Scenario context audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=campaign_usd_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="USD Campaign", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=campaign_eur_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="EUR Allocation", objective_key="retention",
                channel="store", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Scenario reviewer {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            CRMMarketingBudgetScenario(
                id=scenario_id, tenant_id=tenant_id, organization_unit_id=root_id,
                name="Observed performance context", status="draft",
            ),
            CRMMarketingBudgetScenarioLine(
                tenant_id=tenant_id, organization_unit_id=root_id,
                scenario_id=scenario_id, campaign_id=campaign_usd_id,
                planned_budget_amount=Decimal("900"), planned_budget_currency="USD",
            ),
            CRMMarketingBudgetScenarioLine(
                tenant_id=tenant_id, organization_unit_id=root_id,
                scenario_id=scenario_id, campaign_id=campaign_eur_id,
                planned_budget_amount=Decimal("250"), planned_budget_currency="EUR",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_usd_id, measured_on=date(2026, 10, 2),
                source_label="scenario-context", leads=12, conversions=3,
                actual_spend_amount=Decimal("200"), actual_spend_currency="USD",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_eur_id, measured_on=date(2026, 10, 2),
                source_label="scenario-context", leads=6, conversions=1,
                actual_spend_amount=Decimal("30"), actual_spend_currency="USD",
            ),
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id,
                permission_key="crm.budget_scenario:view",
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id,
                permission_key="crm.campaign:view",
            ),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/crm/budget-scenarios/{scenario_id}/performance-context",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={"period_start": "2026-10-01", "period_end": "2026-10-03"},
        )
        assert response.status_code == 200, response.text
        report = response.json()

    assert report["period_calendar_days"] == 3
    assert report["currency_conversion_applied"] is False
    assert report["causal_attribution_applied"] is False
    assert report["automatic_recommendation_issued"] is False
    assert report["metric_definitions"]["actual_spend"]["key"] == "actual_spend"
    allocations = {item["campaign_name"]: item for item in report["allocations"]}
    usd = allocations["USD Campaign"]
    assert usd["actual_spend_in_allocation_currency"] == "200.000000"
    assert usd["budget_variance_amount"] == "700.000000"
    assert usd["budget_used_percent"] == "22.22"
    assert usd["spend_recorded_day_coverage_percent"] == "33.33"
    assert usd["metrics"]["leads"]["actual"] == 12
    assert usd["metrics"]["leads"]["recorded_day_coverage_percent"] == "33.33"

    eur = allocations["EUR Allocation"]
    assert eur["recorded_spend_by_currency"] == {"USD": "30.000000"}
    assert eur["actual_spend_in_allocation_currency"] is None
    assert eur["budget_variance_amount"] is None
    assert eur["metrics"]["leads"]["actual"] == 6

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        audits = (await context.session.scalars(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key == "crm_marketing_budget_scenario.performance_context_viewed",
            AuditEvent.target_key == str(scenario_id),
        ))).all()
        assert len(audits) == 1
