from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select

from funnel_crm.api.v1.integrations import VerifiedProductConnection, router
from funnel_crm.platform.integration_payload_crypto import IntegrationPayloadKeyring
from funnel_crm.platform.models import (
    CRMCustomerActivity,
    CRMProfile,
    IntegrationEventInbox,
    TenantRecord,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_product_app(connection: VerifiedProductConnection, session_factory) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    app.state.integration_payload_keyring = IntegrationPayloadKeyring(
        active_key_id="test-v1", keys={"test-v1": b"t" * 32}
    )
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def inject_verified_product(request: Request, call_next):
        request.state.verified_product_connection = connection
        return await call_next(request)

    return app


@pytest.mark.asyncio
async def test_connected_product_activity_is_projected_once_to_existing_crm_profile(
    runtime_session_factory,
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    profile_id = uuid4()

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(TenantRecord(
            id=profile_id, tenant_id=tenant_id,
            organization_unit_id=root_id, record_type="crm_profile",
        ))
        await context.session.flush()
        context.session.add(CRMProfile(
            id=profile_id, tenant_id=tenant_id, organization_unit_id=root_id,
            record_type="crm_profile", profile_kind="person",
            display_name="Existing lead", lifecycle_stage="lead",
            merged_into_profile_id=None, archived_at=None,
        ))
        await context.session.flush()

    connection = VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=tenant_id,
        source_product="funnel.ads",
        allowed_event_types=frozenset({"customer.activity.recorded"}),
        supported_contract_versions=frozenset({("funnel.customer-activity", 1)}),
    )
    app = make_product_app(connection, runtime_session_factory)
    event_id, correlation_id = uuid4(), uuid4()
    event_body = {
        "event_id": str(event_id),
        "tenant_id": str(tenant_id),
        "source_product": "funnel.ads",
        "event_type": "customer.activity.recorded",
        "contract_name": "funnel.customer-activity",
        "contract_version": 1,
        "correlation_id": str(correlation_id),
        "occurred_at": datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc).isoformat(),
        "payload": {
            "profile_id": str(profile_id),
            "activity_type": "campaign.lead_captured",
            "channel": "online",
            "source_record_id": "ads-lead-1042",
        },
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/api/v1/integrations/events", json=event_body)
        assert first.status_code == 202, first.text
        assert first.json()["projection_status"] == "projected"
        duplicate = await client.post("/api/v1/integrations/events", json=event_body)
        assert duplicate.status_code == 202, duplicate.text
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["projection_status"] == "not_claimed"

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        activities = (await context.session.scalars(
            select(CRMCustomerActivity).where(
                CRMCustomerActivity.tenant_id == tenant_id,
                CRMCustomerActivity.source_product == "funnel.ads",
                CRMCustomerActivity.source_event_id == event_id,
            )
        )).all()
        assert len(activities) == 1
        assert activities[0].profile_id == profile_id
        assert activities[0].activity_type == "campaign.lead_captured"
        assert activities[0].channel == "online"
        inbox = await context.session.scalar(
            select(IntegrationEventInbox).where(
                IntegrationEventInbox.tenant_id == tenant_id,
                IntegrationEventInbox.event_id == event_id,
            )
        )
        assert inbox is not None
        assert inbox.processing_status == "processed"
        assert inbox.processed_at is not None
