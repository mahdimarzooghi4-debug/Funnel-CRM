from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_custom_field_values import router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomFieldDefinition,
    CRMProfile,
    CRMProfileCustomFieldValue,
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
async def test_custom_profile_fields_validate_types_and_redact_values_from_audit(
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
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
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
                display_name="Custom field test",
                lifecycle_stage="lead",
            )
        )
        context.session.add_all(
            [
                CRMCustomFieldDefinition(
                    tenant_id=tenant_id,
                    entity_kind="person",
                    field_key="store_tier",
                    display_name="Store tier",
                    value_type="choice",
                    options=["basic", "vip"],
                ),
                CRMCustomFieldDefinition(
                    tenant_id=tenant_id,
                    entity_kind="person",
                    field_key="visit_count",
                    display_name="Visit count",
                    value_type="number",
                    options=[],
                ),
                CRMCustomFieldDefinition(
                    tenant_id=tenant_id,
                    entity_kind="person",
                    field_key="member_active",
                    display_name="Member active",
                    value_type="boolean",
                    options=[],
                ),
                CRMCustomFieldDefinition(
                    tenant_id=tenant_id,
                    entity_kind="person",
                    field_key="birthday",
                    display_name="Birthday",
                    value_type="date",
                    options=[],
                ),
                CRMCustomFieldDefinition(
                    tenant_id=tenant_id,
                    entity_kind="person",
                    field_key="private_note",
                    display_name="Private note",
                    value_type="text",
                    options=[],
                ),
                CRMCustomFieldDefinition(
                    tenant_id=tenant_id,
                    entity_kind="organization",
                    field_key="tax_category",
                    display_name="Tax category",
                    value_type="text",
                    options=[],
                ),
            ]
        )
        role = Role(tenant_id=tenant_id, name="Custom field operator")
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
                        "crm.custom_field:view",
                        "crm.custom_field:update",
                    )
                ],
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    transport = httpx.ASGITransport(app=app)
    headers = {"X-Workspace-ID": str(tenant_id)}
    path = f"/api/v1/crm/profiles/{profile_id}/custom-fields"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        initial = await client.get(path, headers=headers)
        assert initial.status_code == 200
        assert len(initial.json()["items"]) == 5
        assert all(item["value"] is None for item in initial.json()["items"])

        for key, value in (
            ("store_tier", "vip"),
            ("visit_count", 7),
            ("member_active", True),
            ("birthday", "1990-02-03"),
            ("private_note", "sensitive customer detail"),
        ):
            response = await client.put(f"{path}/{key}", headers=headers, json={"value": value})
            assert response.status_code == 200
            assert response.json()["value"] == value

        invalid_choice = await client.put(
            f"{path}/store_tier", headers=headers, json={"value": "unknown"}
        )
        assert invalid_choice.status_code == 422
        invalid_number = await client.put(
            f"{path}/visit_count", headers=headers, json={"value": True}
        )
        assert invalid_number.status_code == 422
        invalid_date = await client.put(
            f"{path}/birthday", headers=headers, json={"value": "03/02/1990"}
        )
        assert invalid_date.status_code == 422
        wrong_profile_kind = await client.put(
            f"{path}/tax_category", headers=headers, json={"value": "A"}
        )
        assert wrong_profile_kind.status_code == 404

        updated = await client.put(
            f"{path}/private_note",
            headers=headers,
            json={"value": "revised sensitive detail"},
        )
        assert updated.status_code == 200

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        stored = (
            await context.session.scalars(
                select(CRMProfileCustomFieldValue).where(
                    CRMProfileCustomFieldValue.tenant_id == tenant_id,
                    CRMProfileCustomFieldValue.profile_id == profile_id,
                )
            )
        ).all()
        assert len(stored) == 5
        assert next(item for item in stored if item.value == "vip")
        audits = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_type == "crm_profile_custom_field_value",
                )
            )
        ).all()
        assert len(audits) == 6
        serialized = str(
            [
                (event.before_state, event.after_state)
                for event in audits
            ]
        )
        assert "sensitive customer detail" not in serialized
        assert "revised sensitive detail" not in serialized
        assert all(
            "value" not in (event.after_state or {})
            for event in audits
        )
        await context.session.delete(await context.session.get(TenantRecord, profile_id))


@pytest.mark.asyncio
async def test_custom_profile_field_update_requires_its_own_permission(
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
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
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
                display_name="Restricted custom field",
                lifecycle_stage="lead",
            )
        )
        context.session.add(
            CRMCustomFieldDefinition(
                tenant_id=tenant_id,
                entity_kind="person",
                field_key="segment",
                display_name="Segment",
                value_type="text",
                options=[],
            )
        )
        role = Role(tenant_id=tenant_id, name="Profile only viewer")
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
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key="crm.profile:view",
                ),
            ]
        )
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/crm/profiles/{profile_id}/custom-fields",
            headers={"X-Workspace-ID": str(tenant_id)},
        )
        assert response.status_code == 403

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        await context.session.delete(await context.session.get(TenantRecord, profile_id))
