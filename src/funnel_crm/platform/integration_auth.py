"""API-key authentication for tenant-scoped connected products."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.api.v1.integrations import VerifiedProductConnection
from funnel_crm.platform.models import ProductConnection, ProductConnectionCredential

_TOKEN = re.compile(
    r"^fc1_([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})\.([A-Za-z0-9_-]{43})$"
)


def issue_product_credential() -> tuple[UUID, bytes, str]:
    """Return credential ID, digest for persistence, and the one-time raw token."""
    credential_id = uuid4()
    secret = secrets.token_urlsafe(32)
    token = f"fc1_{credential_id}.{secret}"
    return credential_id, hashlib.sha256(secret.encode("utf-8")).digest(), token


async def authenticate_product_credential(
    session_factory: async_sessionmaker[Any] | None,
    *,
    tenant_id: UUID,
    authorization: str | None,
) -> VerifiedProductConnection | None:
    """Validate a bearer token under the tenant selector from the event envelope.

    The claimed tenant is only a lookup scope. A credential must independently
    match a live connection row in that tenant before it yields any grants.
    """
    if session_factory is None or authorization is None:
        return None
    if not authorization.startswith("Bearer "):
        return None
    match = _TOKEN.fullmatch(authorization[7:].strip())
    if match is None:
        return None
    try:
        credential_id = UUID(match.group(1))
    except ValueError:
        return None
    presented_digest = hashlib.sha256(match.group(2).encode("utf-8")).digest()

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            credential = await session.scalar(
                select(ProductConnectionCredential).where(
                    ProductConnectionCredential.tenant_id == tenant_id,
                    ProductConnectionCredential.credential_id == credential_id,
                )
            )
            if (
                credential is None
                or credential.revoked_at is not None
                or not hmac.compare_digest(
                    credential.credential_digest,
                    presented_digest,
                )
            ):
                return None
            connection = await session.scalar(
                select(ProductConnection).where(
                    ProductConnection.tenant_id == tenant_id,
                    ProductConnection.id == credential.connection_id,
                    ProductConnection.revoked_at.is_(None),
                )
            )
            if connection is None:
                return None
            contract_grants = frozenset(
                (str(item["contract_name"]), int(item["contract_version"]))
                for item in connection.contract_grants
            )
            return VerifiedProductConnection(
                connection_id=connection.id,
                tenant_id=connection.tenant_id,
                source_product=connection.source_product,
                allowed_event_types=frozenset(connection.allowed_event_types),
                supported_contract_versions=contract_grants,
                active=True,
            )
