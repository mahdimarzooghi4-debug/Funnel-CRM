"""Tenant-administered product connection credentials and grants."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.integration_auth import issue_product_credential
from funnel_crm.platform.models import (
    AuditEvent,
    CRMConsentProductSyncCheckpoint,
    CRMConsentProductSyncOutbox,
    CRMConsentProductSyncSequence,
    ProductConnection,
    ProductConnectionCredential,
    Workspace,
)
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


class ProductConsentSyncHealthItem(BaseModel):
    connection_id: UUID
    source_product: str
    status: str
    produced_sequence: int
    acknowledged_sequence: int
    pending_count: int
    checkpoint_updated_at: datetime | None


class ProductConsentSyncHealthRead(BaseModel):
    items: list[ProductConsentSyncHealthItem]
    pending_total: int
    behind_product_count: int


class ProductConnectionCreated(ProductConnectionRead):
    credential_id: UUID
    credential: str


class ProductConnectionCredentialRead(BaseModel):
    credential_id: UUID
    created_at: datetime
    revoked_at: datetime | None


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


@router.get(
    "/consent-sync",
    response_model=ProductConsentSyncHealthRead,
    operation_id="listProductConsentSyncHealth",
    summary="List consent feed synchronization health for connected products",
)
async def list_product_consent_sync_health(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> ProductConsentSyncHealthRead:
    """Show each granted product's produced, acknowledged, and pending feed state."""
    root_id = await _require_manage(context)
    tenant_id = context.access.tenant_id
    required_grant = [
        {
            "contract_name": "crm.customer.communication_consent_changes",
            "contract_version": 1,
        }
    ]
    connections = (
        await context.session.scalars(
            select(ProductConnection)
            .where(
                ProductConnection.tenant_id == tenant_id,
                ProductConnection.revoked_at.is_(None),
                ProductConnection.contract_grants.contains(required_grant),
            )
            .order_by(ProductConnection.source_product, ProductConnection.created_at)
        )
    ).all()
    products = list(dict.fromkeys(connection.source_product for connection in connections))
    if not products:
        result = ProductConsentSyncHealthRead(items=[], pending_total=0, behind_product_count=0)
    else:
        sequences = (
            await context.session.scalars(
                select(CRMConsentProductSyncSequence).where(
                    CRMConsentProductSyncSequence.tenant_id == tenant_id,
                    CRMConsentProductSyncSequence.recipient_product.in_(products),
                )
            )
        ).all()
        checkpoints = (
            await context.session.scalars(
                select(CRMConsentProductSyncCheckpoint).where(
                    CRMConsentProductSyncCheckpoint.tenant_id == tenant_id,
                    CRMConsentProductSyncCheckpoint.recipient_product.in_(products),
                )
            )
        ).all()
        pending_rows = (
            await context.session.execute(
                select(
                    CRMConsentProductSyncOutbox.recipient_product,
                    func.count().label("pending_count"),
                )
                .outerjoin(
                    CRMConsentProductSyncCheckpoint,
                    and_(
                        CRMConsentProductSyncCheckpoint.tenant_id
                        == CRMConsentProductSyncOutbox.tenant_id,
                        CRMConsentProductSyncCheckpoint.recipient_product
                        == CRMConsentProductSyncOutbox.recipient_product,
                    ),
                )
                .where(
                    CRMConsentProductSyncOutbox.tenant_id == tenant_id,
                    CRMConsentProductSyncOutbox.recipient_product.in_(products),
                    CRMConsentProductSyncOutbox.sequence
                    > func.coalesce(CRMConsentProductSyncCheckpoint.last_acked_sequence, 0),
                )
                .group_by(CRMConsentProductSyncOutbox.recipient_product)
            )
        ).all()
        sequence_by_product = {
            row.recipient_product: row.last_sequence for row in sequences
        }
        checkpoint_by_product = {
            row.recipient_product: row for row in checkpoints
        }
        pending_by_product = {
            product: count for product, count in pending_rows
        }
        items = []
        for connection in connections:
            product = connection.source_product
            produced = sequence_by_product.get(product, 0)
            checkpoint = checkpoint_by_product.get(product)
            acknowledged = checkpoint.last_acked_sequence if checkpoint else 0
            pending = pending_by_product.get(product, 0)
            items.append(
                ProductConsentSyncHealthItem(
                    connection_id=connection.id,
                    source_product=product,
                    status="behind" if pending else "in_sync",
                    produced_sequence=produced,
                    acknowledged_sequence=acknowledged,
                    pending_count=pending,
                    checkpoint_updated_at=checkpoint.updated_at if checkpoint else None,
                )
            )
        result = ProductConsentSyncHealthRead(
            items=items,
            pending_total=sum(item.pending_count for item in items),
            behind_product_count=sum(item.status == "behind" for item in items),
        )

    context.session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="product_connection.consent_sync_status.listed",
            target_type="workspace",
            target_key=str(tenant_id),
            organization_unit_id=root_id,
            before_state=None,
            after_state={
                "connection_count": len(result.items),
                "behind_product_count": result.behind_product_count,
                "pending_total": result.pending_total,
            },
            correlation_id=None,
        )
    )
    return result


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
    context.session.add(
        ProductConnectionCredential(
            tenant_id=context.access.tenant_id,
            credential_id=credential_id,
            connection_id=connection.id,
            credential_digest=digest,
        )
    )
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
        credential_id=credential_id,
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
    "/{connection_id}/rotate-credential",
    response_model=ProductConnectionCreated,
    operation_id="rotateProductConnectionCredential",
    summary="Replace a product credential and return the new token once",
)
async def rotate_product_connection_credential(
    connection_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> ProductConnectionCreated:
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
    if connection.revoked_at is not None:
        raise HTTPException(status_code=409, detail="A revoked product connection cannot be rotated")

    credential_id, digest, raw_credential = issue_product_credential()
    context.session.add(
        ProductConnectionCredential(
            tenant_id=context.access.tenant_id,
            credential_id=credential_id,
            connection_id=connection.id,
            credential_digest=digest,
        )
    )
    await context.session.flush()
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="product_connection.credential_rotated",
            target_type="product_connection",
            target_key=str(connection.id),
            organization_unit_id=root_id,
            before_state=None,
            after_state={"credential_id": str(credential_id)},
            correlation_id=None,
        )
    )
    await context.session.flush()
    return ProductConnectionCreated(
        **_read(connection).model_dump(),
        credential_id=credential_id,
        credential=raw_credential,
    )



@router.get(
    "/{connection_id}/credentials",
    response_model=list[ProductConnectionCredentialRead],
    operation_id="listProductConnectionCredentials",
    summary="List credential IDs and revocation state without exposing secrets",
)
async def list_product_connection_credentials(
    connection_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[ProductConnectionCredentialRead]:
    await _require_manage(context)
    connection = await context.session.scalar(
        select(ProductConnection.id).where(
            ProductConnection.tenant_id == context.access.tenant_id,
            ProductConnection.id == connection_id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Product connection not found")
    rows = (
        await context.session.scalars(
            select(ProductConnectionCredential)
            .where(
                ProductConnectionCredential.tenant_id == context.access.tenant_id,
                ProductConnectionCredential.connection_id == connection_id,
            )
            .order_by(
                ProductConnectionCredential.created_at,
                ProductConnectionCredential.credential_id,
            )
        )
    ).all()
    return [
        ProductConnectionCredentialRead(
            credential_id=row.credential_id,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )
        for row in rows
    ]


@router.post(
    "/{connection_id}/credentials/{credential_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revokeProductConnectionCredential",
    summary="Revoke one credential while preserving another active credential",
)
async def revoke_product_connection_credential(
    connection_id: UUID,
    credential_id: UUID,
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
    if connection.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Product connection is already revoked")

    credential = await context.session.scalar(
        select(ProductConnectionCredential)
        .where(
            ProductConnectionCredential.tenant_id == context.access.tenant_id,
            ProductConnectionCredential.connection_id == connection_id,
            ProductConnectionCredential.credential_id == credential_id,
        )
        .with_for_update()
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Product credential not found")
    if credential.revoked_at is not None:
        return

    active_count = await context.session.scalar(
        select(func.count(ProductConnectionCredential.credential_id)).where(
            ProductConnectionCredential.tenant_id == context.access.tenant_id,
            ProductConnectionCredential.connection_id == connection_id,
            ProductConnectionCredential.revoked_at.is_(None),
        )
    )
    if active_count is not None and active_count <= 1:
        raise HTTPException(
            status_code=409,
            detail="At least one active product credential must remain",
        )

    credential.revoked_at = datetime.now(timezone.utc)
    await context.session.flush()
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="product_connection.credential_revoked",
            target_type="product_connection_credential",
            target_key=str(credential.credential_id),
            organization_unit_id=root_id,
            before_state={"revoked": False},
            after_state={"revoked": True, "connection_id": str(connection_id)},
            correlation_id=None,
        )
    )
    await context.session.flush()


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
