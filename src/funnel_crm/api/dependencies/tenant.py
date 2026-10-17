"""Resolve a selected workspace only after trusted identity membership checks."""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException, Request

from funnel_crm.platform.tenant_context import (
    AuthenticatedIdentity,
    TenantSessionContext,
    WorkspaceAccessDenied,
    tenant_session,
)


async def require_tenant_session(
    request: Request,
) -> AsyncIterator[TenantSessionContext]:
    """Yield a tenant-scoped session for a verified identity and active member.

    X-Workspace-ID selects a candidate workspace; it is never treated as
    authorization. The authentication layer must populate request.state with
    claims it has already verified cryptographically.
    """
    identity = getattr(request.state, "authenticated_identity", None)
    if not isinstance(identity, AuthenticatedIdentity):
        raise HTTPException(status_code=401, detail="Authentication required")

    raw_tenant_id = request.headers.get("X-Workspace-ID")
    try:
        requested_tenant_id = UUID(raw_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="A valid workspace selection is required") from exc

    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Workspace data service is unavailable")

    try:
        async with tenant_session(
            session_factory,
            requested_tenant_id=requested_tenant_id,
            identity=identity,
        ) as context:
            yield context
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=403, detail="Active workspace membership required") from exc
