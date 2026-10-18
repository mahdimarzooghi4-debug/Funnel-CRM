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
    CRMCustomerActivity,
    CRMProfile,
    ProductConnection,
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



def activity_body(tenant_id: UUID, *, event_id: UUID, external_id: str) -> dict:
    event = body(
        tenant_id,
        event_id=event_id,
        external_id=external_id,
        display_name="unused",
    )
    event["event_type"] = "customer.activity.recorded"
    event["contract_name"] = "crm.customer.activity"
    event["payload"] = {
        "external_customer_id": external_id,
        "activity_type": "order.completed",
        "channel": "online",
        "source_record_id": "order-71",
    }
    return event


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
        allowed_event_types=frozenset({"customer.upserted", "customer.activity.recorded"}),
        supported_contract_versions=frozenset({("crm.customer", 1), ("crm.customer.activity", 1)}),
    )
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        context.session.add(
            ProductConnection(
                id=connection.connection_id,
                tenant_id=tenant_id,
                credential_id=uuid4(),
                credential_digest=b"d" * 32,
                source_product="funnel.store",
                allowed_event_types=["customer.upserted", "customer.activity.recorded"],
                contract_grants=[
                    {"contract_name": "crm.customer", "contract_version": 1},
                    {"contract_name": "crm.customer.activity", "contract_version": 1}
                ],
            )
        )
        await context.session.flush()

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

        activity_event = uuid4()
        activity_response = await client.post(
            "/api/v1/integrations/events",
            json=activity_body(
                tenant_id,
                event_id=activity_event,
                external_id="store-customer-71",
            ),
        )
        assert activity_response.status_code == 202
        activity_result = await consumer.process_batch(tenant_id)
        assert activity_result.claimed == 1
        assert activity_result.processed == 1
        assert activity_result.failed == 0

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
        activities = (
            await context.session.scalars(
                select(CRMCustomerActivity).where(
                    CRMCustomerActivity.tenant_id == tenant_id,
                    CRMCustomerActivity.profile_id == profile.id,
                )
            )
        ).all()
        assert len(activities) == 1
        assert activities[0].activity_type == "order.completed"
        assert activities[0].channel == "online"
        assert activities[0].source_record_id == "order-71"
        assert activities[0].source_event_id == activity_event
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
                    AuditEvent.action_key.in_(["integration.customer.upserted", "integration.customer.activity_recorded"]),
                )
            )
        ).all()
        assert len(audits) == 3
        assert all("contact" not in str(audit.after_state).lower() or "contact_count" in audit.after_state for audit in audits)
