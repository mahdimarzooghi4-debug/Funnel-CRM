from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from funnel_crm.api.v1.integrations import VerifiedProductConnection, router
from funnel_crm.platform.commerce_event_sync import PostgresProductCommerceEventConsumer
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCommunicationConsentEvent,
    CRMMarketingCampaign,
    CRMProfile,
    CRMProfileSegment,
    CRMProductCommerceEvent,
    ProductConnection,
    ProductCustomerIdentity,
    TenantRecord,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(connection: VerifiedProductConnection, session_factory) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    app.state.integration_payload_keyring = IntegrationPayloadKeyring(
        active_key_id="payload-v1", keys={"payload-v1": b"p" * 32}
    )

    @app.middleware("http")
    async def inject_connection(request, call_next):
        request.state.verified_product_connection = connection
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    return app


def order_event(tenant_id: UUID, event_id: UUID, event_type: str, *, kind: str) -> dict:
    return {
        "event_id": str(event_id),
        "tenant_id": str(tenant_id),
        "source_product": "funnel.store",
        "event_type": event_type,
        "contract_name": "crm.commerce.order",
        "contract_version": 1,
        "correlation_id": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "external_customer_id": "store-customer-71",
            "order_reference": "order-71",
            "amount": "129.500000",
            "currency": "USD",
        },
    }


@pytest.mark.asyncio
async def test_paid_and_refunded_product_events_become_real_crm_commerce_facts(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    identity = tenant_case["identity"]
    root_id = tenant_case["root_a"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    connection = VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id,
        source_product="funnel.store",
        allowed_event_types=frozenset({
            "commerce.order.paid", "commerce.order.refunded",
        }),
        supported_contract_versions=frozenset({("crm.commerce.order", 1)}),
    )
    profile_id = uuid4()
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        segment_id = uuid4()
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name="Commerce audience", criteria={},
        ))
        context.session.add(TenantRecord(
            id=profile_id, tenant_id=tenant_id,
            organization_unit_id=root_id, record_type="crm_profile",
        ))
        await context.session.flush()
        context.session.add_all([
            CRMProfile(
                id=profile_id, tenant_id=tenant_id,
                organization_unit_id=root_id, profile_kind="person",
                display_name="Store Customer", lifecycle_stage="customer",
            ),
            ProductCustomerIdentity(
                tenant_id=tenant_id, source_product="funnel.store",
                external_customer_id="store-customer-71", profile_id=profile_id,
            ),
            ProductConnection(
                id=connection.connection_id, tenant_id=tenant_id,
                credential_id=uuid4(), credential_digest=b"d" * 32,
                source_product="funnel.store",
                allowed_event_types=["commerce.order.paid", "commerce.order.refunded"],
                contract_grants=[{"contract_name": "crm.commerce.order", "contract_version": 1}],
            ),
        ])
        await context.session.flush()

    app = make_app(connection, runtime_session_factory)
    keyring = app.state.integration_payload_keyring
    paid_id, refund_id = uuid4(), uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for event_id, event_type, kind in (
            (paid_id, "commerce.order.paid", "paid"),
            (refund_id, "commerce.order.refunded", "refunded"),
        ):
            response = await client.post(
                "/api/v1/integrations/events",
                json=order_event(tenant_id, event_id, event_type, kind=kind),
            )
            assert response.status_code == 202

        consumer = PostgresProductCommerceEventConsumer(
            runtime_session_factory, payload_keyring=keyring
        )
        result = await consumer.process_batch(tenant_id)
        assert result.claimed == 2
        assert result.processed == 2
        assert result.failed == 0

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        facts = (
            await context.session.scalars(
                select(CRMProductCommerceEvent).where(
                    CRMProductCommerceEvent.tenant_id == tenant_id
                )
            )
        ).all()
        assert {fact.event_kind for fact in facts} == {"paid", "refunded"}
        assert all(fact.profile_id == profile_id for fact in facts)
        assert all(fact.amount == Decimal("129.500000") for fact in facts)
        assert {fact.source_event_id for fact in facts} == {paid_id, refund_id}
        assert all(fact.order_reference == "order-71" for fact in facts)

        consent_count = await context.session.scalar(
            select(func.count()).select_from(CRMCommunicationConsentEvent).where(
                CRMCommunicationConsentEvent.tenant_id == tenant_id,
                CRMCommunicationConsentEvent.profile_id == profile_id,
            )
        )
        assert consent_count == 0

        audits = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action_key == "integration.commerce.order_recorded",
                )
            )
        ).all()
        assert len(audits) == 2
        assert all("order_reference" not in audit.after_state for audit in audits)
        assert all("amount" not in audit.after_state for audit in audits)

        # Keep the shared tenant fixture clean: commerce facts reference profiles.
        for fact in facts:
            await context.session.delete(fact)
