from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_measurement_imports import router
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingMeasurementImportBatch,
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
async def test_campaign_measurement_csv_preview_atomic_import_and_idempotent_replay(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id, campaign_id = uuid4(), uuid4()
    existing_measurement_id = uuid4()
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(
            CRMProfileSegment(
                id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
                name=f"CSV import audience {uuid4().hex[:8]}",
                criteria={"profile_kinds": ["person"]}, is_active=True,
            )
        )
        await context.session.flush()
        context.session.add(
            CRMMarketingCampaign(
                id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Imported campaign", objective_key="retention",
                channel="store", planned_budget_amount=Decimal("400"),
                planned_budget_currency="USD", starts_at=None, ends_at=None, status="draft",
            )
        )
        await context.session.flush()
        context.session.add(
            CRMMarketingCampaignMeasurement(
                id=existing_measurement_id, tenant_id=tenant_id,
                organization_unit_id=root_id, campaign_id=campaign_id,
                measured_on=date(2026, 10, 16), source_label="old report",
                impressions=90, reach=70, clicks=6, responses=None, leads=1,
                conversions=0, actual_spend_amount=Decimal("10"),
                actual_spend_currency="USD", attributed_revenue_amount=None,
                attributed_revenue_currency=None,
            )
        )
        role = Role(tenant_id=tenant_id, name=f"CSV campaign manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all(
            [
                RoleAssignment(
                    tenant_id=tenant_id, membership_id=context.access.membership_id,
                    role_id=role.id, organization_unit_id=root_id,
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.campaign:view",
                ),
                RolePermission(
                    tenant_id=tenant_id, role_id=role.id,
                    permission_key="crm.campaign:manage",
                ),
            ]
        )
        await context.session.flush()

    csv_content = chr(65279) + (
        "measured_on,source_label,impressions,reach,clicks,responses,leads,conversions,assigned_count,exposure_count,"
        "actual_spend_amount,actual_spend_currency,attributed_revenue_amount,attributed_revenue_currency\n"
        "2026-10-16,Social report,100,80,10,3,2,1,95,90,15,USD,75,USD\n"
        "2026-10-17,Store report,,50,,4,,1,,,8,EUR,,\n"
    )
    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    base = f"/api/v1/crm/campaigns/{campaign_id}/measurements"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        template = await client.get(f"{base}/import-template", headers=headers)
        assert template.status_code == 200
        assert template.text.startswith("measured_on,source_label")
        assert "assigned_count,exposure_count" in template.text

        preview = await client.post(
            f"{base}/import-preview",
            headers=headers,
            json={"csv_content": csv_content},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["valid"] is True, preview.json()
        assert preview.json()["row_count"] == 2
        assert preview.json()["would_create"] == 1
        assert preview.json()["would_update"] == 1
        assert preview.json()["rows"][0]["assigned_count"] == 95
        assert preview.json()["rows"][0]["exposure_count"] == 90

        imported = await client.post(
            f"{base}/import",
            headers=headers,
            json={"idempotency_key": "monthly-export-2026-10", "csv_content": csv_content},
        )
        assert imported.status_code == 200, imported.text
        first_result = imported.json()
        assert first_result["created_count"] == 1
        assert first_result["updated_count"] == 1
        assert first_result["replayed"] is False

        replay = await client.post(
            f"{base}/import",
            headers=headers,
            json={"idempotency_key": "monthly-export-2026-10", "csv_content": csv_content},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["batch_id"] == first_result["batch_id"]
        assert replay.json()["replayed"] is True

        changed_replay = await client.post(
            f"{base}/import",
            headers=headers,
            json={
                "idempotency_key": "monthly-export-2026-10",
                "csv_content": csv_content.replace("Social report,100,", "Social report,101,"),
            },
        )
        assert changed_replay.status_code == 409

        invalid_csv = csv_content.replace("Social report,100,", "Social report,-1,")
        invalid_preview = await client.post(
            f"{base}/import-preview", headers=headers, json={"csv_content": invalid_csv}
        )
        assert invalid_preview.status_code == 200
        assert invalid_preview.json()["valid"] is False
        assert invalid_preview.json()["errors"]
        invalid_import = await client.post(
            f"{base}/import",
            headers=headers,
            json={"idempotency_key": "invalid-export", "csv_content": invalid_csv},
        )
        assert invalid_import.status_code == 422

        duplicate_date_csv = csv_content + (
            "2026-10-16,Duplicate,1,,,,,,,,,\n"
        )
        duplicate_preview = await client.post(
            f"{base}/import-preview",
            headers=headers,
            json={"csv_content": duplicate_date_csv},
        )
        assert duplicate_preview.status_code == 200
        assert duplicate_preview.json()["valid"] is False
        assert any("Duplicate measured_on" in error["detail"] for error in duplicate_preview.json()["errors"])

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        row_count = await context.session.scalar(
            select(func.count()).select_from(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == tenant_id,
                CRMMarketingCampaignMeasurement.campaign_id == campaign_id,
            )
        )
        assert row_count == 2
        corrected = await context.session.scalar(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == tenant_id,
                CRMMarketingCampaignMeasurement.id == existing_measurement_id,
            )
        )
        assert corrected is not None
        assert corrected.source_label == "Social report"
        assert corrected.impressions == 100
        assert corrected.assigned_count == 95
        assert corrected.exposure_count == 90
        assert corrected.actual_spend_currency == "USD"
        batch_count = await context.session.scalar(
            select(func.count()).select_from(CRMMarketingMeasurementImportBatch).where(
                CRMMarketingMeasurementImportBatch.tenant_id == tenant_id,
                CRMMarketingMeasurementImportBatch.campaign_id == campaign_id,
            )
        )
        assert batch_count == 1
        campaign = await context.session.scalar(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == tenant_id,
                CRMMarketingCampaign.id == campaign_id,
            )
        )
        assert campaign is not None
        assert (campaign.planned_budget_amount, campaign.planned_budget_currency) == (
            Decimal("400"), "USD"
        )
