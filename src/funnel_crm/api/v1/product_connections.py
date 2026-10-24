"""Tenant-administered product connection credentials and grants."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.integration_auth import issue_product_credential
from funnel_crm.platform.models import AuditEvent, ProductConnection, Workspace
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/integrations/connections", tags=["product connections"])


class ProductContractGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_name: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9._-]*$")
    contract_version: int = Field(ge=1, le=2_147_483_647)


class ProductConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_product: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    allowed_event_types: list[str] = Field(min_length=1, max_length=50)
    contract_grants: list[ProductContractGrant] = Field(min_length=1, max_length=50)

    @field_validator("allowed_event_types")
    @classmethod
    def validate_event_types(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[a-z][a-z0-9_.-]{2,119}", value) for value in values):
            raise ValueError("event types must be stable lowercase identifiers")
        if len(values) != len(set(values)):
            raise ValueError("event types must be unique")
        return values

    @model_validator(mode="after")
    def unique_contract_grants(self) -> "ProductConnectionCreate":
        keys = [(grant.contract_name, grant.contract_version) for grant in self.contract_grants]
        if len(keys) != len(set(keys)):
            raise ValueError("contract grants must be unique")
        return self


class ProductConnectionRead(BaseModel):
    id: UUID
    source_product: str
    allowed_event_types: list[str]
    contract_grants: list[ProductContractGrant]
    created_at: datetime
    revoked_at: datetime | None


class ProductConnectionCreated(ProductConnectionRead):
    credential: str


async def _require_manage(context: TenantSessionContext) -> UUID:
    tenant_id = context.access.tenant_id
    root_id = await context.session.scalar(
        select(Workspace.root_organization_id).where(Workspace.id == tenant_id)
    )
    if root_id is None or not await has_crm_permission(
        context,
        permission_key="crm.integration:manage",
        organization_unit_id=root_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Product connection management is not authorized",
        )
    return root_id


def _audit(
    context: TenantSessionContext,
    *,
    action_key: str,
    connection: ProductConnection,
    root_id: UUID,
) -> None:
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key=action_key,
            target_type="product_connection",
            target_key=str(connection.id),
            organization_unit_id=root_id,
            before_state=None,
            after_state={
                "source_product": connection.source_product,
                "credential_id": str(connection.credential_id),
                "revoked": connection.revoked_at is not None,
                "allowed_event_count": len(connection.allowed_event_types),
                "contract_grant_count": len(connection.contract_grants),
            },
            correlation_id=None,
        )
    )


def _read(connection: ProductConnection) -> ProductConnectionRead:
    return ProductConnectionRead(
        id=connection.id,
        source_product=connection.source_product,
        allowed_event_types=connection.allowed_event_types,
        contract_grants=[
            ProductContractGrant.model_validate(grant)
            for grant in connection.contract_grants
        ],
        created_at=connection.created_at,
        revoked_at=connection.revoked_at,
    )


@router.post(
    "",
    response_model=ProductConnectionCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProductConnection",
    summary="Create a tenant-scoped product credential and explicit grants",
)
async def create_product_connection(
    payload: ProductConnectionCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> ProductConnectionCreated:
    root_id = await _require_manage(context)
    credential_id, digest, raw_credential = issue_product_credential()
    connection = ProductConnection(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        credential_id=credential_id,
        credential_digest=digest,
        source_product=payload.source_product,
        allowed_event_types=payload.allowed_event_types,
        contract_grants=[grant.model_dump() for grant in payload.contract_grants],
    )
    context.session.add(connection)
    await context.session.flush()
    _audit(
        context,
        action_key="product_connection.created",
        connection=connection,
        root_id=root_id,
    )
    await context.session.flush()
    return ProductConnectionCreated(
        **_read(connection).model_dump(),
        credential=raw_credential,
    )


@router.get(
    "",
    response_model=list[ProductConnectionRead],
    operation_id="listProductConnections",
    summary="List connected products without exposing credentials",
)
async def list_product_connections(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[ProductConnectionRead]:
    await _require_manage(context)
    rows = (
        await context.session.scalars(
            select(ProductConnection)
            .where(ProductConnection.tenant_id == context.access.tenant_id)
            .order_by(ProductConnection.created_at.desc(), ProductConnection.id)
        )
    ).all()
    return [_read(row) for row in rows]


@router.post(
    "/{connection_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revokeProductConnection",
    summary="Revoke a tenant-scoped product credential",
)
async def revoke_product_connection(
    connection_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    root_id = await _require_manage(context)
    connection = await context.session.scalar(
        select(ProductConnection)
        .where(
            ProductConnection.tenant_id == context.access.tenant_id,
            ProductConnection.id == connection_id,
        )
        .with_for_update()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Product connection not found")
    if connection.revoked_at is None:
        connection.revoked_at = datetime.now(timezone.utc)
        await context.session.flush()
        _audit(
            context,
            action_key="product_connection.revoked",
            connection=connection,
            root_id=root_id,
        )
        await context.session.flush()
