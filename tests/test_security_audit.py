import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from funnel_crm.platform.models import (
    AuditEvent,
    OrganizationUnit,
    PermissionDefinition,
    Role,
    RoleAssignment,
    RolePermission,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


@pytest.mark.asyncio
async def test_membership_role_permission_and_org_changes_capture_actor_and_diff(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
    db_session: AsyncSession,
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    permission_key = f"audit-test:{uuid4()}"
    admin_engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
    async with admin_factory() as admin:
        async with admin.begin():
            admin.add(
                PermissionDefinition(
                    key=permission_key,
                    description="Temporary permission definition for audit integration test",
                )
            )

    role_id = uuid4()
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        role = Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Marketing operator",
            is_active=True,
        )
        context.session.add(role)
        await context.session.flush()

        context.session.add(
            RolePermission(
                tenant_id=tenant_id,
                role_id=role_id,
                permission_key=permission_key,
            )
        )
        await context.session.flush()

        unit = OrganizationUnit(
            tenant_id=tenant_id,
            parent_id=root_id,
            name="North region",
            unit_type="unit",
        )
        context.session.add(unit)
        await context.session.flush()

        assignment = RoleAssignment(
            tenant_id=tenant_id,
            membership_id=context.access.membership_id,
            role_id=role_id,
            organization_unit_id=unit.id,
        )
        context.session.add(assignment)
        await context.session.flush()

        role.is_active = False
        membership = await context.session.get(
            WorkspaceMembership, context.access.membership_id
        )
        assert membership is not None
        membership.status = "suspended"
        await context.session.flush()

        events = (
            await context.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.target_key.in_(
                        [
                            str(role_id),
                            f"{role_id}:{permission_key}",
                            str(unit.id),
                            str(assignment.id),
                            str(membership.id),
                        ]
                    )
                )
            )
        ).all()

        by_action = {event.action_key: event for event in events}
        expected = {
            "role.created",
            "role.updated",
            "role_permission.created",
            "organization_unit.created",
            "role_assignment.created",
            "workspace_membership.updated",
        }
        assert expected <= set(by_action)
        for event in events:
            assert event.tenant_id == tenant_id
            assert event.actor_kind == "user"
            assert event.actor_identity_id == context.access.identity_id
            assert event.actor_membership_id == context.access.membership_id

        assert by_action["role.created"].before_state is None
        assert by_action["role.created"].after_state["is_active"] is True
        assert by_action["role.updated"].before_state["is_active"] is True
        assert by_action["role.updated"].after_state["is_active"] is False
        assert by_action["workspace_membership.updated"].before_state["status"] == "active"
        assert by_action["workspace_membership.updated"].after_state["status"] == "suspended"
        assert by_action["organization_unit.created"].organization_unit_id == unit.id
        assert by_action["role_assignment.created"].organization_unit_id == unit.id

        role_event_id = by_action["role.created"].event_id

    try:
        # A different tenant cannot read this event even when it knows its id.
        identity_b = tenant_case["identity_b"]
        tenant_b = tenant_case["workspace_b"]
        assert isinstance(identity_b, AuthenticatedIdentity)
        assert isinstance(tenant_b, UUID)
        async with tenant_session(
            runtime_session_factory,
            requested_tenant_id=tenant_b,
            identity=identity_b,
        ) as context_b:
            assert await context_b.session.get(AuditEvent, role_event_id) is None

        # The role has read/append rights only; table triggers independently
        # prevent a privileged owner from changing or deleting committed events.
        async with runtime_session_factory() as session:
            async with session.begin():
                privileges = (
                    await session.execute(
                        text(
                            "SELECT has_table_privilege(current_user, 'audit_events', 'UPDATE') "
                            "AS can_update, "
                            "has_table_privilege(current_user, 'audit_events', 'DELETE') "
                            "AS can_delete"
                        )
                    )
                ).one()
                assert privileges.can_update is False
                assert privileges.can_delete is False

        # Verify the database guard as the privileged test connection. The test
        # transaction is rolled back by db_session after the expected failure.
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        with pytest.raises(DBAPIError):
            await db_session.execute(
                update(AuditEvent)
                .where(AuditEvent.event_id == role_event_id)
                .values(action_key="tampered")
            )

    finally:
        async with admin_factory() as admin:
            async with admin.begin():
                await admin.execute(
                    delete(RolePermission).where(
                        RolePermission.tenant_id == tenant_id,
                        RolePermission.permission_key == permission_key,
                    )
                )
                await admin.execute(
                    delete(PermissionDefinition).where(
                        PermissionDefinition.key == permission_key
                    )
                )
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_audit_rows_are_not_visible_without_tenant_context(
    runtime_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with runtime_session_factory() as session:
        async with session.begin():
            assert (await session.scalars(select(AuditEvent))).all() == []
