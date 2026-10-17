from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomFieldDefinition,
    CRMProfile,
    CRMPipeline,
    TenantRecord,
    WorkspaceCRMSettings,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


@pytest.mark.asyncio
async def test_workspace_settings_and_customer_profile_are_tenant_scoped_and_audited(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    other_tenant_id = tenant_case["workspace_b"]
    organization_id = tenant_case["root_a"]
    other_organization_id = tenant_case["root_b"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(other_tenant_id, UUID)
    assert isinstance(organization_id, UUID)
    assert isinstance(other_organization_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    profile_id = uuid4()
    pipeline_id = uuid4()
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        settings = await context.session.get(WorkspaceCRMSettings, tenant_id)
        assert settings is not None
        assert settings.business_models == ["general"]

        settings.business_models = ["b2b", "retail"]
        settings.configuration_version = 2
        context.session.add(
            CRMPipeline(
                id=pipeline_id,
                tenant_id=tenant_id,
                pipeline_key="lead-qualification",
                entity_kind="lead",
                display_name="Lead qualification",
                stages=[
                    {"key": "new", "label": "New"},
                    {"key": "qualified", "label": "Qualified"},
                ],
                is_default=True,
            )
        )
        context.session.add(
            CRMCustomFieldDefinition(
                tenant_id=tenant_id,
                entity_kind="organization",
                field_key="market_segment",
                display_name="Market segment",
                value_type="choice",
                options=["local", "national"],
                is_required=False,
            )
        )
        context.session.add(
            TenantRecord(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_id,
                record_type="crm_profile",
            )
        )
        context.session.add(
            CRMProfile(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_id,
                profile_kind="person",
                display_name="Test Contact A",
                lifecycle_stage="lead",
            )
        )
        await context.session.flush()

        profile = await context.session.get(CRMProfile, profile_id)
        assert profile is not None
        assert profile.display_name == "Test Contact A"

        # RLS blocks a row that claims ownership by a different Workspace.
        async with context.session.begin_nested():
            foreign_id = uuid4()
            context.session.add(
                TenantRecord(
                    id=foreign_id,
                    tenant_id=other_tenant_id,
                    organization_unit_id=other_organization_id,
                    record_type="crm_profile",
                )
            )
            context.session.add(
                CRMProfile(
                    id=foreign_id,
                    tenant_id=other_tenant_id,
                    organization_unit_id=other_organization_id,
                    profile_kind="organization",
                    display_name="Foreign contact",
                )
            )
            with pytest.raises(DBAPIError):
                await context.session.flush()

        # The composite organization FK rejects a foreign organizational scope.
        async with context.session.begin_nested():
            foreign_scope_id = uuid4()
            context.session.add(
                TenantRecord(
                    id=foreign_scope_id,
                    tenant_id=tenant_id,
                    organization_unit_id=organization_id,
                    record_type="crm_profile",
                )
            )
            context.session.add(
                CRMProfile(
                    id=foreign_scope_id,
                    tenant_id=tenant_id,
                    organization_unit_id=other_organization_id,
                    profile_kind="organization",
                    display_name="Wrong scope",
                )
            )
            with pytest.raises(DBAPIError):
                await context.session.flush()

        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_key.in_([str(tenant_id), str(pipeline_id), str(profile_id)]),
                )
            )
        ).all()
        by_target = {event.target_key: event for event in events}
        assert by_target[str(tenant_id)].action_key == "workspace_crm_settings.updated"
        assert by_target[str(tenant_id)].actor_identity_id == context.access.identity_id
        assert by_target[str(pipeline_id)].action_key == "crm_pipeline.created"
        profile_event = by_target[str(profile_id)]
        assert profile_event.action_key == "crm_profile.created"
        assert profile_event.after_state == {
            "profile_kind": "person",
            "lifecycle_stage": "lead",
        }
        assert "display_name" not in profile_event.after_state

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=other_tenant_id,
        identity=tenant_case["identity_b"],
    ) as other_context:
        assert await other_context.session.get(CRMProfile, profile_id) is None
        assert await other_context.session.get(WorkspaceCRMSettings, tenant_id) is None


@pytest.mark.asyncio
async def test_crm_pipeline_and_custom_field_constraints_are_enforced(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        context.session.add(
            CRMPipeline(
                tenant_id=tenant_id,
                pipeline_key="empty",
                entity_kind="lead",
                display_name="Empty pipeline",
                stages=[],
            )
        )
        with pytest.raises(DBAPIError):
            await context.session.flush()

        async with context.session.begin_nested():
            context.session.add(
                CRMCustomFieldDefinition(
                    tenant_id=tenant_id,
                    entity_kind="person",
                    field_key="bad-key",
                    display_name="Bad key",
                    value_type="text",
                )
            )
            with pytest.raises(DBAPIError):
                await context.session.flush()


@pytest.mark.asyncio
async def test_crm_records_are_hidden_without_tenant_context(
    runtime_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with runtime_session_factory() as session:
        async with session.begin():
            assert (await session.scalars(select(CRMProfile))).all() == []
            assert (await session.scalars(select(CRMPipeline))).all() == []
