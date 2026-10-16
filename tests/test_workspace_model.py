from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from funnel_crm.platform.models import OrganizationUnit, Workspace
from funnel_crm.platform.workspaces import create_workspace


@pytest.mark.asyncio
async def test_workspace_is_created_with_its_own_root_organization(
    db_session: AsyncSession,
) -> None:
    workspace = await create_workspace(db_session, display_name="  فروشگاه نمونه  ")

    assert workspace.display_name == "فروشگاه نمونه"
    root = await db_session.scalar(
        select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == workspace.id,
            OrganizationUnit.id == workspace.root_organization_id,
        )
    )

    assert root is not None
    assert root.unit_type == "root"
    assert root.parent_id is None
    assert root.name == workspace.display_name


@pytest.mark.asyncio
async def test_organization_parent_from_another_tenant_is_rejected(
    db_session: AsyncSession,
) -> None:
    first = await create_workspace(db_session, display_name="Workspace A")
    second = await create_workspace(db_session, display_name="Workspace B")
    child = OrganizationUnit(
        id=uuid4(),
        tenant_id=first.id,
        parent_id=second.root_organization_id,
        name="Invalid cross-tenant child",
        unit_type="unit",
    )
    db_session.add(child)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_workspace_cannot_reference_another_tenants_root(
    db_session: AsyncSession,
) -> None:
    second = await create_workspace(db_session, display_name="Workspace B")
    forged = Workspace(
        id=uuid4(),
        display_name="Forged workspace",
        root_organization_id=second.root_organization_id,
        root_organization_type="root",
    )
    db_session.add(forged)
    await db_session.execute(
        text("SET CONSTRAINTS fk_workspaces_root_organization_same_tenant IMMEDIATE")
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
