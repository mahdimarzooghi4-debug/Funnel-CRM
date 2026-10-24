from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_commerce_outcomes import router as outcomes_router
from funnel_crm.api.v1.integrations import (
    VerifiedProductConnection,
    router as integrations_router,
)
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.integration_processing import PostgresProductEventProcessor
from funnel_crm.platform.commerce_orders import PostgresCommerceOrderEventConsumer
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMProfile,
    CRMProfileSegment,
    CRMProductCommerceEvent,
    IntegrationEventInbox,
    Role,
    RoleAssignment,
    RolePermission,
    TenantRecord,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    identity: AuthenticatedIdentity,
    connection: VerifiedProductConnection,
) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    app.state.integration_payload_keyring = IntegrationPayloadKeyring(
        active_key_id="test-v1", keys={"test-v1": b"c" * 32}
    )
    app.include_router(integrations_router, prefix="/api/v1")
    app.include_router(outcomes_router, prefix="/api/v1")

    @app.middleware("http")
    async def inject_test_identities(request: Request, call_next):
        request.state.authenticated_identity = identity
        request.state.verified_product_connection = connection
        return await call_next(request)

    return app


@pytest.mark.asyncio
async def test_paid_and_refund_events_are_deduplicated_scoped_and_reported_separately(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    profile_id, segment_id, campaign_id = uuid4(), uuid4(), uuid4()
    event_ids = [uuid4(), uuid4()]
    connection = VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id,
        source_product="funnel.store",
        allowed_event_types=frozenset({
            "commerce.order.paid",
            "commerce.order.refunded",
        }),
        supported_contract_versions=frozenset({("commerce.order", 1)}),
    )
    app = make_app(runtime_session_factory, identity, connection)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(TenantRecord(
            id=profile_id, tenant_id=tenant_id, organization_unit_id=root_id,
            record_type="crm_profile",
        ))
        await context.session.flush()
        context.session.add(CRMProfile(
            id=profile_id, tenant_id=tenant_id, organization_unit_id=root_id,
            profile_kind="person", display_name="Commerce test customer",
            lifecycle_stage="customer",
        ))
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Commerce test segment {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        role = Role(tenant_id=tenant_id, name=f"Commerce analyst {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Commerce test campaign",
                objective_key="acquisition", channel="store",
                planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
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
                permission_key="crm.commerce_event:view",
            ),
        ])
        await context.session.flush()

    envelope_payloads = [
        {
            "organization_unit_id": str(root_id),
            "campaign_id": str(campaign_id),
            "profile_id": str(profile_id),
            "order_reference": "ORDER-42",
            "amount": "125.50",
            "currency": "USD",
        },
        {
            "organization_unit_id": str(root_id),
            "campaign_id": str(campaign_id),
            "profile_id": str(profile_id),
            "order_reference": "ORDER-42",
            "amount": "25.00",
            "currency": "USD",
        },
    ]
    event_types = ["commerce.order.paid", "commerce.order.refunded"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first_receipt = None
        for index, payload in enumerate(envelope_payloads):
            body = {
                "event_id": str(event_ids[index]),
                "tenant_id": str(tenant_id),
                "source_product": "funnel.store",
                "event_type": event_types[index],
                "contract_name": "commerce.order",
                "contract_version": 1,
                "correlation_id": str(uuid4()),
                "occurred_at": "2026-10-19T12:00:00+00:00",
                "payload": payload,
            }
            response = await client.post("/api/v1/integrations/events", json=body)
            assert response.status_code == 202, response.text
            if index == 0:
                first_receipt = response.json()
                duplicate = await client.post("/api/v1/integrations/events", json=body)
                assert duplicate.status_code == 202, duplicate.text
                assert duplicate.json()["duplicate"] is True
        assert first_receipt is not None

    processor = PostgresProductEventProcessor(
        runtime_session_factory, keyring=app.state.integration_payload_keyring
    )
    claims = await processor.claim(
        tenant_id, limit=10, contract_name="commerce.order", contract_version=1
    )
    assert len(claims) == 2
    consumer = PostgresCommerceOrderEventConsumer(runtime_session_factory)
    results = [await consumer.consume(claim) for claim in claims]
    assert results == [True, True]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/crm/analytics/commerce-outcomes",
            headers={"X-Workspace-ID": str(tenant_id)},
            params={
                "organization_unit_id": str(root_id),
                "period_start": "2026-10-19",
                "period_end": "2026-10-19",
            },
        )
        assert response.status_code == 200, response.text
        report = response.json()

    assert report["paid_event_count"] == 1
    assert report["refund_event_count"] == 1
    assert "net_revenue" not in report
    assert len(report["buckets"]) == 2
    by_kind = {row["event_kind"]: row for row in report["buckets"]}
    assert by_kind["paid"]["event_count"] == 1
    assert by_kind["paid"]["distinct_order_count"] == 1
    assert Decimal(by_kind["paid"]["amount_total"]) == Decimal("125.50")
    assert by_kind["refunded"]["event_count"] == 1
    assert by_kind["refunded"]["distinct_order_count"] == 1
    assert Decimal(by_kind["refunded"]["amount_total"]) == Decimal("25.00")

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        facts = (await context.session.scalars(
            select(CRMProductCommerceEvent).where(
                CRMProductCommerceEvent.tenant_id == tenant_id,
                CRMProductCommerceEvent.source_event_id.in_(event_ids),
            )
        )).all()
        assert len(facts) == 2
        inbox_rows = (await context.session.scalars(
            select(IntegrationEventInbox).where(
                IntegrationEventInbox.tenant_id == tenant_id,
                IntegrationEventInbox.event_id.in_(event_ids),
            )
        )).all()
        assert len(inbox_rows) == 2
        assert all(row.processing_status == "processed" for row in inbox_rows)
        audits = (await context.session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "crm_commerce_event.report_viewed",
            )
        )).all()
        assert len(audits) == 1

        await context.session.execute(delete(CRMProductCommerceEvent).where(
            CRMProductCommerceEvent.tenant_id == tenant_id,
            CRMProductCommerceEvent.source_event_id.in_(event_ids),
        ))
        await context.session.execute(delete(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        ))
        await context.session.execute(delete(CRMProfile).where(
            CRMProfile.tenant_id == tenant_id, CRMProfile.id == profile_id,
        ))
        await context.session.execute(delete(CRMProfileSegment).where(
            CRMProfileSegment.tenant_id == tenant_id,
            CRMProfileSegment.id == segment_id,
        ))
        await context.session.execute(delete(TenantRecord).where(
            TenantRecord.tenant_id == tenant_id, TenantRecord.id == profile_id,
        ))
