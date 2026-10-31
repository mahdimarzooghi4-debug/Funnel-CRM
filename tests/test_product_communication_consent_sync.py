from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
    CRMConsentProductSyncOutbox,
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


def consent_event(
    tenant_id: UUID,
    event_id: UUID,
    decision: str = "withdrawn",
    occurred_at: datetime | None = None,
) -> dict:
    return {
        "event_id": str(event_id),
        "tenant_id": str(tenant_id),
        "source_product": "funnel.store",
        "event_type": "customer.communication_consent.changed",
        "contract_name": "crm.customer.communication_consent",
        "contract_version": 1,
        "correlation_id": str(uuid4()),
        "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
        "payload": {
            "external_customer_id": "store-customer-71",
            "purpose_key": "product_updates",
            "channel": "email",
            "decision": decision,
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
            ("crm.customer.communication_consent_changes", 1),
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
                    {
                        "contract_name": "crm.customer.communication_consent_changes",
                        "contract_version": 1,
                    },
                ],
            ),
        ])
        await context.session.flush()

    app = make_app(connection, runtime_session_factory)
    keyring = app.state.integration_payload_keyring
    withdrawn_at = datetime.now(timezone.utc)
    event_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/integrations/events",
            json=consent_event(tenant_id, event_id, occurred_at=withdrawn_at),
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
        assert datetime.fromisoformat(eligibility.json()["decision_at"]) == withdrawn_at

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
            "decision_at": None,
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

        batch = await client.post(
            "/api/v1/integrations/communication-eligibility/check-batch",
            json={
                "tenant_id": str(tenant_id),
                "checks": [
                    {
                        "reference": "withdrawal-1",
                        "external_customer_id": "store-customer-71",
                        "purpose_key": "product_updates",
                        "channel": "email",
                    },
                    {
                        "reference": "unknown-purpose",
                        "external_customer_id": "store-customer-71",
                        "purpose_key": "product_reviews",
                        "channel": "email",
                    },
                    {
                        "reference": "unmapped",
                        "external_customer_id": "unmapped-customer",
                        "purpose_key": "product_updates",
                        "channel": "email",
                    },
                ],
            },
        )
        assert batch.status_code == 200
        batch_items = batch.json()["checks"]
        assert [item["reference"] for item in batch_items] == [
            "withdrawal-1", "unknown-purpose", "unmapped",
        ]
        assert [item["status"] for item in batch_items] == [
            "withdrawn", "unknown", "unknown",
        ]
        assert [item["allowed"] for item in batch_items] == [False, False, False]
        assert batch_items[0]["consent_event_id"] == eligibility.json()["consent_event_id"]
        assert batch_items[0]["policy_version"] == "2026-01"
        assert datetime.fromisoformat(batch_items[0]["decision_at"]) == withdrawn_at
        assert batch_items[1]["consent_event_id"] is None

        too_many_checks = await client.post(
            "/api/v1/integrations/communication-eligibility/check-batch",
            json={
                "tenant_id": str(tenant_id),
                "checks": [
                    {
                        "reference": f"ref-{index}",
                        "external_customer_id": "store-customer-71",
                        "purpose_key": "product_updates",
                        "channel": "email",
                    }
                    for index in range(101)
                ],
            },
        )
        assert too_many_checks.status_code == 422

        duplicate_references = await client.post(
            "/api/v1/integrations/communication-eligibility/check-batch",
            json={
                "tenant_id": str(tenant_id),
                "checks": [
                    {
                        "reference": "same",
                        "external_customer_id": "store-customer-71",
                        "purpose_key": "product_updates",
                        "channel": "email",
                    },
                    {
                        "reference": "same",
                        "external_customer_id": "unmapped-customer",
                        "purpose_key": "product_updates",
                        "channel": "email",
                    },
                ],
            },
        )
        assert duplicate_references.status_code == 422

    granted_at = withdrawn_at + timedelta(seconds=1)
    granted_event_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        granted_event = await client.post(
            "/api/v1/integrations/events",
            json=consent_event(
                tenant_id, granted_event_id, decision="granted", occurred_at=granted_at
            ),
        )
        assert granted_event.status_code == 202
    granted_result = await consumer.process_batch(tenant_id)
    assert granted_result.claimed == 1
    assert granted_result.processed == 1
    assert granted_result.failed == 0

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        granted_eligibility = await client.post(
            "/api/v1/integrations/communication-eligibility/check",
            json={
                "tenant_id": str(tenant_id),
                "external_customer_id": "store-customer-71",
                "purpose_key": "product_updates",
                "channel": "email",
            },
        )
        assert granted_eligibility.status_code == 200
        assert granted_eligibility.json()["status"] == "granted"
        assert granted_eligibility.json()["allowed"] is True
        assert granted_eligibility.json()["policy_version"] == "2026-01"
        assert granted_eligibility.json()["source_product"] == "funnel.store"
        assert datetime.fromisoformat(granted_eligibility.json()["decision_at"]) == granted_at

        granted_batch = await client.post(
            "/api/v1/integrations/communication-eligibility/check-batch",
            json={
                "tenant_id": str(tenant_id),
                "checks": [{
                    "reference": "granted-1",
                    "external_customer_id": "store-customer-71",
                    "purpose_key": "product_updates",
                    "channel": "email",
                }],
            },
        )
        assert granted_batch.status_code == 200
        granted_item = granted_batch.json()["checks"][0]
        assert granted_item["reference"] == "granted-1"
        assert granted_item["status"] == "granted"
        assert granted_item["allowed"] is True
        assert granted_item["consent_event_id"] == granted_eligibility.json()["consent_event_id"]
        assert granted_item["policy_version"] == "2026-01"
        assert granted_item["source_product"] == "funnel.store"
        assert datetime.fromisoformat(granted_item["decision_at"]) == granted_at

    stale_event_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        stale_event = await client.post(
            "/api/v1/integrations/events",
            json=consent_event(
                tenant_id, stale_event_id, occurred_at=withdrawn_at - timedelta(seconds=1)
            ),
        )
        assert stale_event.status_code == 202
    stale_result = await consumer.process_batch(tenant_id)
    assert stale_result.processed == 1
    assert stale_result.failed == 0

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        after_stale_single = await client.post(
            "/api/v1/integrations/communication-eligibility/check",
            json={
                "tenant_id": str(tenant_id),
                "external_customer_id": "store-customer-71",
                "purpose_key": "product_updates",
                "channel": "email",
            },
        )
        after_stale_batch = await client.post(
            "/api/v1/integrations/communication-eligibility/check-batch",
            json={
                "tenant_id": str(tenant_id),
                "checks": [{
                    "reference": "after-stale",
                    "external_customer_id": "store-customer-71",
                    "purpose_key": "product_updates",
                    "channel": "email",
                }],
            },
        )
        assert after_stale_single.json()["status"] == "granted"
        assert after_stale_single.json()["consent_event_id"] == granted_eligibility.json()["consent_event_id"]
        assert after_stale_batch.json()["checks"][0]["status"] == "granted"
        assert after_stale_batch.json()["checks"][0]["consent_event_id"] == granted_eligibility.json()["consent_event_id"]

        first_changes = await client.post(
            "/api/v1/integrations/communication-consent/changes",
            json={
                "tenant_id": str(tenant_id),
                "after_sequence": 0,
                "limit": 2,
            },
        )
        assert first_changes.status_code == 200
        first_page = first_changes.json()
        assert [item["sequence"] for item in first_page["changes"]] == [1, 2]
        assert [item["decision"] for item in first_page["changes"]] == [
            "withdrawn", "granted",
        ]
        assert all(
            item["external_customer_id"] == "store-customer-71"
            for item in first_page["changes"]
        )
        assert first_page["next_sequence"] == 2
        assert first_page["has_more"] is True

        second_changes = await client.post(
            "/api/v1/integrations/communication-consent/changes",
            json={
                "tenant_id": str(tenant_id),
                "after_sequence": first_page["next_sequence"],
                "limit": 2,
            },
        )
        assert second_changes.status_code == 200
        second_page = second_changes.json()
        assert [item["sequence"] for item in second_page["changes"]] == [3]
        assert second_page["changes"][0]["decision"] == "withdrawn"
        assert second_page["changes"][0]["source_event_id"] == str(stale_event_id)
        assert second_page["next_sequence"] == 3
        assert second_page["has_more"] is False

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        consents = (
            await context.session.scalars(
                select(CRMCommunicationConsentEvent).where(
                    CRMCommunicationConsentEvent.tenant_id == tenant_id,
                    CRMCommunicationConsentEvent.profile_id == profile_id,
                )
            )
        ).all()
        assert len(consents) == 3
        assert {
            (consent.source_event_id, consent.decision, consent.decision_at)
            for consent in consents
        } == {
            (event_id, "withdrawn", withdrawn_at),
            (granted_event_id, "granted", granted_at),
            (stale_event_id, "withdrawn", withdrawn_at - timedelta(seconds=1)),
        }
        assert all(consent.purpose_key == "product_updates" for consent in consents)
        assert all(consent.channel == "email" for consent in consents)
        assert all(consent.source_product == "funnel.store" for consent in consents)
        audit_count = await context.session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "integration.communication_consent.recorded",
            )
        )
        assert audit_count == 3
        eligibility_audits = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action_key == "integration.communication_eligibility.checked",
                )
            )
        ).all()
        assert len(eligibility_audits) == 8
        assert sum(event.after_state["check_count"] for event in eligibility_audits) == 10
        assert sum(event.after_state["granted_count"] for event in eligibility_audits) == 4
        assert sum(event.after_state["withdrawn_count"] for event in eligibility_audits) == 2
        assert sum(event.after_state["unknown_count"] for event in eligibility_audits) == 4
        assert all(
            "external_customer_id" not in event.after_state
            for event in eligibility_audits
        )
        assert all(
            event.target_type == "product_connection"
            and event.target_key == str(connection.connection_id)
            for event in eligibility_audits
        )
        change_audits = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action_key == "integration.communication_consent.changes_read",
                )
            )
        ).all()
        assert len(change_audits) == 2
        assert all(
            "external_customer_id" not in event.after_state for event in change_audits
        )
        outbox_count = await context.session.scalar(
            select(func.count()).select_from(CRMConsentProductSyncOutbox).where(
                CRMConsentProductSyncOutbox.tenant_id == tenant_id,
                CRMConsentProductSyncOutbox.recipient_product == "funnel.store",
            )
        )
        assert outbox_count == 3

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
        occurred_at=withdrawn_at,
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
        await consumer._process_one(replace(
            replay, occurred_at=replay.occurred_at + timedelta(seconds=2)
        ))
    with pytest.raises(ConsentSyncError, match="crm.consent.invalid_event_time"):
        await consumer._process_one(replace(
            replay, occurred_at=datetime.now(timezone.utc) + timedelta(days=1)
        ))
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
        ) == 3
        assert await context.session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action_key == "integration.communication_consent.recorded",
            )
        ) == 3
