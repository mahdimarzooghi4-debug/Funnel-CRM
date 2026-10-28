from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_segments import router
from funnel_crm.api.v1.crm_communication_consent import router as consent_router
from funnel_crm.platform.models import (
    AuditEvent, CRMCommunicationConsentEvent, CRMContactPoint, CRMCustomerActivity,
    CRMProfile, CRMProfileSegment, Role, RoleAssignment, RolePermission, TenantRecord,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory: async_sessionmaker[AsyncSession], identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    app.include_router(consent_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_saved_segment_previews_scoped_profiles_and_records_audit(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    profile_id = uuid4()
    async with tenant_session(runtime_session_factory, requested_tenant_id=tenant_id, identity=identity) as context:
        context.session.add(
            TenantRecord(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                record_type="crm_profile",
            )
        )
        await context.session.flush()
        context.session.add(
            CRMProfile(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                profile_kind="person",
                display_name="Segment test profile",
                lifecycle_stage="lead",
            )
        )
        await context.session.flush()
        context.session.add(
            CRMCustomerActivity(
                id=uuid4(),
                tenant_id=tenant_id,
                profile_id=profile_id,
                source_product="funnel.store",
                source_event_id=uuid4(),
                activity_type="order.completed",
                channel="online",
                source_record_id="order-segment-1",
                occurred_at=datetime.now(timezone.utc) - timedelta(days=5),
            )
        )
        role = Role(tenant_id=tenant_id, name=f"Segment manager {profile_id.hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all(
            [
                RoleAssignment(
                    tenant_id=tenant_id,
                    membership_id=context.access.membership_id,
                    role_id=role.id,
                    organization_unit_id=root_id,
                ),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.profile:view"),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.segment:view"),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.segment:manage"),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.contact_point:view"),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.communication_consent:view"),
                RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.communication_consent:record"),
            ]
        )
        context.session.add(CRMContactPoint(
            id=uuid4(),
            tenant_id=tenant_id,
            profile_id=profile_id,
            channel="email",
            encrypted_value=b"x" * 29,
            encryption_key_id="test-key",
            fingerprint_key_id=None,
            match_fingerprint=None,
            verification_status="verified",
            is_primary=True,
        ))
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/crm/segments",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "New leads",
                "criteria": {"profile_kinds": ["person"], "lifecycle_stages": ["lead"]},
            },
        )
        assert created.status_code == 201
        segment_id = created.json()["id"]

        listed = await client.get("/api/v1/crm/segments", headers=headers)
        assert listed.status_code == 200
        assert any(item["id"] == segment_id for item in listed.json()["items"])

        preview = await client.get(f"/api/v1/crm/segments/{segment_id}/preview", headers=headers)
        assert preview.status_code == 200
        assert preview.json()["total"] == 1
        assert preview.json()["items"][0]["id"] == str(profile_id)

        grant = await client.post(
            f"/api/v1/crm/profiles/{profile_id}/communication-consents",
            headers=headers,
            json={
                "purpose_key": "marketing",
                "channel": "email",
                "decision": "granted",
                "policy_version": "v1",
            },
        )
        assert grant.status_code == 201, grant.text
        reach = await client.get(
            f"/api/v1/crm/segments/{segment_id}/reach",
            headers=headers,
            params={"purpose_key": "marketing", "channel": "email"},
        )
        assert reach.status_code == 200, reach.text
        assert reach.json()["total_profiles"] == 1
        assert reach.json()["profiles_with_verified_contact"] == 1
        assert reach.json()["eligible_profiles"] == 1

        withdrawal = await client.post(
            f"/api/v1/crm/profiles/{profile_id}/communication-consents",
            headers=headers,
            json={
                "purpose_key": "marketing",
                "channel": "email",
                "decision": "withdrawn",
                "policy_version": "v1",
            },
        )
        assert withdrawal.status_code == 201, withdrawal.text
        withdrawn_reach = await client.get(
            f"/api/v1/crm/segments/{segment_id}/reach",
            headers=headers,
            params={"purpose_key": "marketing", "channel": "email"},
        )
        assert withdrawn_reach.status_code == 200, withdrawn_reach.text
        assert withdrawn_reach.json()["eligible_profiles"] == 0
        assert withdrawn_reach.json()["withdrawn_consent_profiles"] == 1

        updated = await client.patch(
            f"/api/v1/crm/segments/{segment_id}",
            headers=headers,
            json={"criteria": {"profile_kinds": ["person"], "lifecycle_stages": ["customer"]}},
        )
        assert updated.status_code == 200
        preview_after_update = await client.get(
            f"/api/v1/crm/segments/{segment_id}/preview",
            headers=headers,
        )
        assert preview_after_update.status_code == 200
        assert preview_after_update.json()["total"] == 0

        activity_criteria = await client.patch(
            f"/api/v1/crm/segments/{segment_id}",
            headers=headers,
            json={
                "criteria": {
                    "activity": {
                        "activity_types": ["order.completed"],
                        "channels": ["online"],
                        "within_last_days": 30,
                    }
                }
            },
        )
        assert activity_criteria.status_code == 200
        activity_preview = await client.get(
            f"/api/v1/crm/segments/{segment_id}/preview",
            headers=headers,
        )
        assert activity_preview.status_code == 200
        assert activity_preview.json()["total"] == 1

        include_segment = await client.post(
            "/api/v1/crm/segments",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "Lead audience",
                "criteria": {"profile_kinds": ["person"], "lifecycle_stages": ["lead"]},
            },
        )
        assert include_segment.status_code == 201, include_segment.text
        exclude_segment = await client.post(
            "/api/v1/crm/segments",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "Online purchasers",
                "criteria": {"activity": {"channels": ["online"], "within_last_days": 30}},
            },
        )
        assert exclude_segment.status_code == 201, exclude_segment.text

        composed_segment = await client.post(
            "/api/v1/crm/segments",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "Leads excluding recent online purchasers",
                "criteria": {
                    "include_segment_ids": [include_segment.json()["id"]],
                    "exclude_segment_ids": [exclude_segment.json()["id"]],
                },
            },
        )
        assert composed_segment.status_code == 201, composed_segment.text
        assert composed_segment.json()["criteria"]["include_segment_ids"] == [include_segment.json()["id"]]
        composed_preview = await client.get(
            f"/api/v1/crm/segments/{composed_segment.json()['id']}/preview",
            headers=headers,
        )
        assert composed_preview.status_code == 200, composed_preview.text
        assert composed_preview.json()["total"] == 0

        referenced_deactivation = await client.post(
            f"/api/v1/crm/segments/{exclude_segment.json()['id']}/deactivate",
            headers=headers,
        )
        assert referenced_deactivation.status_code == 409

        invalid_nested = await client.post(
            "/api/v1/crm/segments",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "name": "Nested segment",
                "criteria": {"include_segment_ids": [composed_segment.json()["id"]]},
            },
        )
        assert invalid_nested.status_code == 422

        no_match_criteria = await client.patch(
            f"/api/v1/crm/segments/{segment_id}",
            headers=headers,
            json={
                "criteria": {
                    "activity": {
                        "activity_types": ["order.refunded"],
                        "channels": ["online"],
                        "within_last_days": 30,
                    }
                }
            },
        )
        assert no_match_criteria.status_code == 200
        no_match_preview = await client.get(
            f"/api/v1/crm/segments/{segment_id}/preview",
            headers=headers,
        )
        assert no_match_preview.status_code == 200
        assert no_match_preview.json()["total"] == 0

        deactivated = await client.post(
            f"/api/v1/crm/segments/{segment_id}/deactivate",
            headers=headers,
        )
        assert deactivated.status_code == 204
        hidden = await client.get("/api/v1/crm/segments", headers=headers)
        assert all(item["id"] != segment_id for item in hidden.json()["items"])
        inactive_preview = await client.get(
            f"/api/v1/crm/segments/{segment_id}/preview",
            headers=headers,
        )
        assert inactive_preview.status_code == 409

    async with tenant_session(runtime_session_factory, requested_tenant_id=tenant_id, identity=identity) as context:
        segment = await context.session.get(CRMProfileSegment, UUID(segment_id))
        assert segment is not None and not segment.is_active
        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "crm_profile_segment",
                    AuditEvent.target_key == segment_id,
                )
            )
        ).all()
        assert {event.action_key for event in events} == {
            "crm_profile_segment.created",
            "crm_profile_segment.updated",
            "crm_profile_segment.previewed",
            "crm_profile_segment.deactivated",
        }
        await context.session.execute(
            delete(TenantRecord).where(TenantRecord.tenant_id == tenant_id, TenantRecord.id == profile_id)
        )
        await context.session.flush()
