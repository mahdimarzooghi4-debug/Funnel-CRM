from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from funnel_crm.api.v1.integrations import VerifiedProductConnection, router
from funnel_crm.platform.communication_consent_sync import (
    ConsentSyncError,
    PostgresProductConsentEventConsumer,
)
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.integration_processing import ClaimedIntegrationEvent
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCommunicationConsentEvent,
    CRMProfile,
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


def consent_event(tenant_id: UUID, event_id: UUID) -> dict:
    return {
        "event_id": str(event_id),
        "tenant_id": str(tenant_id),
        "source_product": "funnel.store",
        "event_type": "customer.communication_consent.changed",
        "contract_name": "crm.customer.communication_consent",
        "contract_version": 1,
        "correlation_id": str(uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "external_customer_id": "store-customer-71",
            "purpose_key": "product_updates",
            "channel": "email",
            "decision": "withdrawn",
            "policy_version": "2026-01",
        },
    }


@pytest.mark.asyncio
async def test_product_consent_event_is_provenanced_and_replay_safe(
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
        allowed_event_types=frozenset({"customer.communication_consent.changed"}),
        supported_contract_versions=frozenset({
            ("crm.customer.communication_consent", 1),
            ("crm.customer.communication_eligibility", 1),
        }),
    )
    profile_id = uuid4()
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
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
                allowed_event_types=["customer.communication_consent.changed"],
                contract_grants=[
                    {
                        "contract_name": "crm.customer.communication_consent",
                        "contract_version": 1,
                    },
                    {
                        "contract_name": "crm.customer.communication_eligibility",
                        "contract_version": 1,
                    },
                ],
            ),
        ])
        await context.session.flush()

    app = make_app(connection, runtime_session_factory)
    keyring = app.state.integration_payload_keyring
    event_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/integrations/events",
            json=consent_event(tenant_id, event_id),
        )
        assert response.status_code == 202

    consumer = PostgresProductConsentEventConsumer(
        runtime_session_factory, payload_keyring=keyring
    )
    result = await consumer.process_batch(tenant_id)
    assert result.claimed == 1
    assert result.processed == 1
    assert result.failed == 0

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        eligibility = await client.post(
            "/api/v1/integrations/communication-eligibility/check",
            json={
                "tenant_id": str(tenant_id),
                "external_customer_id": "store-customer-71",
                "purpose_key": "product_updates",
                "channel": "email",
            },
        )
        assert eligibility.status_code == 200
        assert eligibility.json()["status"] == "withdrawn"
        assert eligibility.json()["allowed"] is False
        assert eligibility.json()["consent_event_id"] > 0
        assert eligibility.json()["policy_version"] == "2026-01"
        assert eligibility.json()["source_product"] == "funnel.store"

        unknown_identity = await client.post(
            "/api/v1/integrations/communication-eligibility/check",
            json={
                "tenant_id": str(tenant_id),
                "external_customer_id": "unmapped-customer",
                "purpose_key": "product_updates",
                "channel": "email",
            },
        )
        assert unknown_identity.status_code == 200
        assert unknown_identity.json() == {
            "status": "unknown",
            "allowed": False,
            "decision": None,
            "consent_event_id": None,
            "policy_version": None,
            "source_product": None,
            "recorded_at": None,
        }

        missing_consent = await client.post(
            "/api/v1/integrations/communication-eligibility/check",
            json={
                "tenant_id": str(tenant_id),
                "external_customer_id": "store-customer-71",
                "purpose_key": "product_reviews",
                "channel": "email",
            },
        )
        assert missing_consent.status_code == 200
        assert missing_consent.json()["status"] == "unknown"
        assert missing_consent.json()["allowed"] is False
        assert missing_consent.json()["consent_event_id"] is None

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        consent = await context.session.scalar(
            select(CRMCommunicationConsentEvent).where(
                CRMCommunicationConsentEvent.tenant_id == tenant_id,
                CRMCommunicationConsentEvent.profile_id == profile_id,
            )
        )
        assert consent is not None
        assert consent.purpose_key == "product_updates"
        assert consent.channel == "email"
        assert consent.decision == "withdrawn"
        assert consent.source_product == "funnel.store"
        assert consent.source_event_id == event_id
        audit_count = await context.session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "integration.communication_consent.recorded",
            )
        )
        assert audit_count == 1

    replay = ClaimedIntegrationEvent(
        id=uuid4(),
        tenant_id=tenant_id,
        connection_id=connection.connection_id,
        event_id=event_id,
        source_product="funnel.store",
        event_type=consumer.EVENT_TYPE,
        contract_name=consumer.CONTRACT_NAME,
        contract_version=consumer.CONTRACT_VERSION,
        correlation_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
        payload={
            "external_customer_id": "store-customer-71",
            "purpose_key": "product_updates",
            "channel": "email",
            "decision": "withdrawn",
            "policy_version": "2026-01",
        },
        attempt_count=2,
        lease_token=uuid4(),
        lease_until=datetime.now(timezone.utc),
    )
    assert await consumer._process_one(replay) is False
    with pytest.raises(ConsentSyncError, match="crm.consent.source_event_conflict"):
        await consumer._process_one(replace(replay, payload={
            **replay.payload, "decision": "granted",
        }))
    with pytest.raises(ConsentSyncError, match="crm.consent.invalid_payload"):
        await consumer._process_one(replace(replay, payload={
            **replay.payload, "unexpected": "value",
        }))

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        assert await context.session.scalar(
            select(func.count()).select_from(CRMCommunicationConsentEvent).where(
                CRMCommunicationConsentEvent.tenant_id == tenant_id,
                CRMCommunicationConsentEvent.profile_id == profile_id,
            )
        ) == 1
        assert await context.session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "integration.communication_consent.recorded",
            )
        ) == 1
