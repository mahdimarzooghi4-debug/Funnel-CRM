from collections.abc import AsyncIterator
import os
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from funnel_crm.platform.models import UserIdentity, Workspace, WorkspaceMembership
from funnel_crm.platform.tenant_context import AuthenticatedIdentity
from funnel_crm.platform.workspaces import create_workspace


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    database_url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with session_factory() as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def runtime_session_factory():
    """Use the actual non-owner, NOBYPASSRLS database role on a one-connection pool."""
    engine = create_async_engine(
        os.environ["TEST_DATABASE_URL"],
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_runtime_role(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET ROLE funnel_crm_runtime")
        cursor.close()

    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def tenant_case() -> AsyncIterator[dict[str, object]]:
    """Create two committed tenants and one active identity per tenant."""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    identity_a = AuthenticatedIdentity(
        issuer="https://identity.example.test",
        subject=f"user-a-{uuid4()}",
    )
    identity_b = AuthenticatedIdentity(
        issuer="https://identity.example.test",
        subject=f"user-b-{uuid4()}",
    )

    async with session_factory() as session:
        async with session.begin():
            workspace_a = await create_workspace(session, display_name="Tenant A")
            workspace_b = await create_workspace(session, display_name="Tenant B")
            user_a = UserIdentity(issuer=identity_a.issuer, subject=identity_a.subject)
            user_b = UserIdentity(issuer=identity_b.issuer, subject=identity_b.subject)
            session.add_all([user_a, user_b])
            await session.flush()
            membership_a = WorkspaceMembership(
                tenant_id=workspace_a.id, identity_id=user_a.id, status="active"
            )
            membership_b = WorkspaceMembership(
                tenant_id=workspace_b.id, identity_id=user_b.id, status="active"
            )
            session.add_all([membership_a, membership_b])
            await session.flush()
            values = {
                "workspace_a": workspace_a.id,
                "workspace_b": workspace_b.id,
                "root_a": workspace_a.root_organization_id,
                "root_b": workspace_b.root_organization_id,
                "identity": identity_a,
                "identity_b": identity_b,
            }

    try:
        yield values
    finally:
        async with session_factory() as session:
            async with session.begin():
                # Tenant-owned rows cascade from workspaces. Identities are global
                # references and are removed after their memberships cascade.
                await session.execute(
                    delete(Workspace).where(
                        Workspace.id.in_([values["workspace_a"], values["workspace_b"]])
                    )
                )
                await session.execute(
                    delete(UserIdentity).where(
                        UserIdentity.id.in_([user_a.id, user_b.id])
                    )
                )
        await engine.dispose()
