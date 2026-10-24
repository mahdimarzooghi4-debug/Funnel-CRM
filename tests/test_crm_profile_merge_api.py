from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_profiles import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMProfile,
    Role,
    RoleAssignment,
    RolePermission,
    TenantRecord,
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
async def test_profile_merge_is_scoped_audited_and_preserves_source_record(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    source_id, target_id, other_kind_id = uuid4(), uuid4(), uuid4()
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        context.session.add_all(
            [
                TenantRecord(
                    id=profile_id,
                    tenant_id=tenant_id,
                    organization_unit_id=root_id,
                    record_type="crm_profile",
                )
                for profile_id in (source_id, target_id, other_kind_id)
            ]
        )
        await context.session.flush()
        context.session.add_all(
            [
                CRMProfile(
                    id=source_id,
                    tenant_id=tenant_id,
                    organization_unit_id=root_id,
                    profile_kind="person",
                    display_name="Duplicate record",
                    lifecycle_stage="lead",
                ),
                CRMProfile(
                    id=target_id,
                    tenant_id=tenant_id,
                    organization_unit_id=root_id,
                    profile_kind="person",
                    display_name="Surviving record",
                    lifecycle_stage="customer",
                ),
                CRMProfile(
                    id=other_kind_id,
                    tenant_id=tenant_id,
                    organization_unit_id=root_id,
                    profile_kind="organization",
                    display_name="Different profile kind",
                    lifecycle_stage="lead",
                ),
            ]
        )
        role = Role(tenant_id=tenant_id, name="Duplicate reviewer")
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
                *[
                    RolePermission(
                        tenant_id=tenant_id,
                        role_id=role.id,
                        permission_key=permission,
                    )
                    for permission in (
                        "crm.profile:view",
                        "crm.profile:update",
                        "crm.profile:review_duplicates",
                    )
                ],
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        merge_path = f"/api/v1/crm/profiles/{source_id}/merge-into/{target_id}"
        merged = await client.post(merge_path, headers=headers)
        assert merged.status_code == 200
        assert merged.json()["merged_into_profile_id"] == str(target_id)

        repeated = await client.post(merge_path, headers=headers)
        assert repeated.status_code == 200

        self_merge = await client.post(
            f"/api/v1/crm/profiles/{source_id}/merge-into/{source_id}",
            headers=headers,
        )
        assert self_merge.status_code == 422

        wrong_kind = await client.post(
            f"/api/v1/crm/profiles/{other_kind_id}/merge-into/{target_id}",
            headers=headers,
        )
        assert wrong_kind.status_code == 409

        page = await client.get("/api/v1/crm/profiles", headers=headers)
        assert page.status_code == 200
        visible_ids = {item["id"] for item in page.json()["items"]}
        assert str(source_id) not in visible_ids
        assert str(target_id) in visible_ids
        assert str(other_kind_id) in visible_ids

        source_read = await client.get(
            f"/api/v1/crm/profiles/{source_id}",
            headers=headers,
        )
        assert source_read.status_code == 200
        assert source_read.json()["merged_into_profile_id"] == str(target_id)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        source = await context.session.get(CRMProfile, source_id)
        assert source is not None
        assert source.display_name == "Duplicate record"
        merge_events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "crm_profile_merge",
                    AuditEvent.target_key == str(source_id),
                )
            )
        ).all()
        assert len(merge_events) == 1
        assert merge_events[0].action_key == "crm_profile.merged"
        assert merge_events[0].after_state == {
            "merged_into_profile_id": str(target_id)
        }

        await context.session.execute(
            delete(TenantRecord).where(
                TenantRecord.tenant_id == tenant_id,
                TenantRecord.id.in_([source_id, target_id, other_kind_id]),
            )
        )
        await context.session.flush()
