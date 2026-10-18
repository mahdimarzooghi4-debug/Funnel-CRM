from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from funnel_crm.api.v1.integrations import VerifiedProductConnection, router
from funnel_crm.platform.contact_point_crypto import ContactPointKeyring
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.integration_processing import PostgresProductEventProcessor
from funnel_crm.platform.customer_profile_sync import PostgresProductEventConsumer
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCommunicationConsentEvent,
    CRMContactPoint,
    CRMProfile,
    ProductCustomerIdentity,
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


def body(tenant_id: UUID, *, event_id: UUID, external_id: str, display_name: str) -> dict:
    return {
        "event_id": str(event_id),
        "tenant_id": str(tenant_id),
        "source_product": "funnel.store",
        "event_type": "customer.upserted",
        "contract_name": "crm.customer",
        "contract_version": 1,
        "correlation_id": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "external_customer_id": external_id,
            "profile_kind": "person",
            "display_name": display_name,
            "contacts": [{"channel": "email", "value": "buyer@example.test"}],
        },
    }


@pytest.mark.asyncio
async def test_customer_upserts_update_one_profile_and_encrypt_contact_points(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    connection = VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id,
        source_product="funnel.store",
        allowed_event_types=frozenset({"customer.upserted"}),
        supported_contract_versions=frozenset({("crm.customer", 1)}),
    )
    app = make_app(connection, runtime_session_factory)
    first_event, second_event = uuid4(), uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/v1/integrations/events",
            json=body(
                tenant_id,
                event_id=first_event,
                external_id="store-customer-71",
                display_name="Samira Customer",
            ),
        )
        assert first.status_code == 202
        consumer = PostgresProductEventConsumer(
            runtime_session_factory,
            payload_keyring=app.state.integration_payload_keyring,
            contact_keyring=ContactPointKeyring(
                active_key_id="contact-v1", keys={"contact-v1": b"c" * 32}
            ),
        )
        first_result = await consumer.process_batch(tenant_id)
        assert first_result.claimed == 1
        assert first_result.processed == 1
        assert first_result.failed == 0

        second = await client.post(
            "/api/v1/integrations/events",
            json=body(
                tenant_id,
                event_id=second_event,
                external_id="store-customer-71",
                display_name="Samira Updated",
            ),
        )
        assert second.status_code == 202
        second_result = await consumer.process_batch(tenant_id)
        assert second_result.processed == 1

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        profile = await context.session.scalar(
            select(CRMProfile).where(
                CRMProfile.tenant_id == tenant_id,
                CRMProfile.display_name == "Samira Updated",
            )
        )
        assert profile is not None
        link_count = await context.session.scalar(
            select(func.count()).select_from(ProductCustomerIdentity).where(
                ProductCustomerIdentity.tenant_id == tenant_id,
                ProductCustomerIdentity.source_product == "funnel.store",
                ProductCustomerIdentity.external_customer_id == "store-customer-71",
            )
        )
        assert link_count == 1
        contacts = (
            await context.session.scalars(
                select(CRMContactPoint).where(
                    CRMContactPoint.tenant_id == tenant_id,
                    CRMContactPoint.profile_id == profile.id,
                )
            )
        ).all()
        assert len(contacts) == 1
        assert contacts[0].verification_status == "unverified"
        assert b"buyer@example.test" not in contacts[0].encrypted_value
        consents = await context.session.scalar(
            select(func.count()).select_from(CRMCommunicationConsentEvent).where(
                CRMCommunicationConsentEvent.tenant_id == tenant_id,
                CRMCommunicationConsentEvent.profile_id == profile.id,
            )
        )
        assert consents == 0
        audits = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action_key == "integration.customer.upserted",
                )
            )
        ).all()
        assert len(audits) == 2
        assert all("contact" not in str(audit.after_state).lower() or "contact_count" in audit.after_state for audit in audits)
