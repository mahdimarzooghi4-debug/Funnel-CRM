from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_experiments import router
from funnel_crm.platform.models import (
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
    return app


@pytest.mark.asyncio
async def test_campaign_experiment_readout_compares_variants_descriptively(
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
    control_id, variant_id = uuid4(), uuid4()
    experiment_id: UUID
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Experiment audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=control_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Control campaign", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=variant_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Variant campaign", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=control_id, measured_on=date(2026, 10, 16),
                source_label="control report", impressions=1000, clicks=100,
                leads=40, conversions=10,
                actual_spend_amount=Decimal("100"), actual_spend_currency="USD",
                attributed_revenue_amount=Decimal("300"), attributed_revenue_currency="USD",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=variant_id, measured_on=date(2026, 10, 16),
                source_label="variant report", impressions=1000, clicks=120,
                leads=50, conversions=15,
                actual_spend_amount=Decimal("90"), actual_spend_currency="USD",
                attributed_revenue_amount=Decimal("360"), attributed_revenue_currency="USD",
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Experiment manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:manage"),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "organization_unit_id": str(root_id),
            "name": "Landing page headline test",
            "hypothesis": "Variant headline may increase completed conversions.",
            "primary_metric": "conversions",
            "guardrails": [{"metric": "clicks"}, {"metric": "roas", "currency": "USD"}],
            "period_start": "2026-10-16",
            "period_end": "2026-10-16",
            "variants": [
                {"campaign_id": str(control_id), "label": "Existing headline", "is_control": True},
                {"campaign_id": str(variant_id), "label": "New headline", "is_control": False},
            ],
        }
        created = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=payload
        )
        assert created.status_code == 201, created.text
        experiment_id = UUID(created.json()["id"])

        listed = await client.get("/api/v1/crm/campaign-experiments", headers=headers)
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert listed.json()[0]["experiment"]["id"] == str(experiment_id)
        assert listed.json()[0]["experiment"]["guardrail_metrics"] == [
            {"metric": "clicks", "currency": None},
            {"metric": "roas", "currency": "USD"},
        ]

        readout = await client.get(
            f"/api/v1/crm/campaign-experiments/{experiment_id}/readout",
            headers=headers,
        )
        assert readout.status_code == 200, readout.text
        result = readout.json()
        assert result["readout_kind"] == "descriptive_observation"
        control, variant = result["variants"]
        assert control["is_control"] is True
        assert control["guardrails"][0]["value"] == 100
        assert Decimal(control["guardrails"][1]["value"]) == Decimal("3")
        assert control["value"] == 10
        assert control["delta_vs_control"] == 0
        assert variant["value"] == 15
        assert variant["delta_vs_control"] == 5
        assert variant["percent_change_vs_control"] == 50.0
        assert variant["observed_days"] == 1
        assert variant["guardrails"][0]["value"] == 120
        assert variant["guardrails"][0]["delta_vs_control"] == 20
        assert variant["guardrails"][0]["percent_change_vs_control"] == 20.0
        assert Decimal(variant["guardrails"][1]["value"]) == Decimal("4")
        assert Decimal(variant["guardrails"][1]["delta_vs_control"]) == Decimal("1")
        assert variant["guardrails"][1]["status"] == "available"

        missing_currency = dict(payload)
        missing_currency["primary_metric"] = "cost_per_conversion"
        invalid = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=missing_currency
        )
        assert invalid.status_code == 422

        missing_control = dict(payload)
        missing_control["variants"] = [
            {"campaign_id": str(control_id), "label": "A", "is_control": False},
            {"campaign_id": str(variant_id), "label": "B", "is_control": False},
        ]
        invalid_control = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=missing_control
        )
        assert invalid_control.status_code == 422

        duplicate_guardrail = dict(payload)
        duplicate_guardrail["guardrails"] = [{"metric": "clicks"}, {"metric": "clicks"}]
        invalid_guardrail = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=duplicate_guardrail
        )
        assert invalid_guardrail.status_code == 422
