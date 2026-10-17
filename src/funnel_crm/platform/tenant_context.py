"""Verified workspace context and transaction-local PostgreSQL tenant state."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.platform.models import UserIdentity, WorkspaceMembership


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Issuer and subject claims already validated by the authentication layer."""

    issuer: str
    subject: str


@dataclass(frozen=True)
class VerifiedWorkspaceAccess:
    tenant_id: UUID
    membership_id: UUID
    identity_id: UUID


@dataclass(frozen=True)
class TenantSessionContext:
    session: AsyncSession
    access: VerifiedWorkspaceAccess


class WorkspaceAccessDenied(Exception):
    """Raised when the authenticated identity has no active workspace membership."""


@asynccontextmanager
async def tenant_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    requested_tenant_id: UUID,
    identity: AuthenticatedIdentity,
) -> AsyncIterator[TenantSessionContext]:
    """Open a transaction after verifying membership for the selected workspace.

    The requested workspace id is only a selector. RLS first limits the
    membership lookup to that workspace; only an active membership for the
    already-authenticated issuer/subject allows the caller to use the session.
    PostgreSQL SET LOCAL state is cleared automatically when this transaction
    commits or rolls back, including when the connection returns to the pool.
    """
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(requested_tenant_id)},
            )
            membership = await session.scalar(
                select(WorkspaceMembership)
                .join(UserIdentity, UserIdentity.id == WorkspaceMembership.identity_id)
                .where(
                    WorkspaceMembership.tenant_id == requested_tenant_id,
                    WorkspaceMembership.status == "active",
                    UserIdentity.issuer == identity.issuer,
                    UserIdentity.subject == identity.subject,
                )
            )
            if membership is None:
                raise WorkspaceAccessDenied

            yield TenantSessionContext(
                session=session,
                access=VerifiedWorkspaceAccess(
                    tenant_id=requested_tenant_id,
                    membership_id=membership.id,
                    identity_id=membership.identity_id,
                ),
            )
