"""Catalog item references captured against sales opportunities."""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent, CRMOpportunity, CRMOpportunityCatalogItem, CRMProductCatalogItem,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/opportunities/{opportunity_id}/catalog-items", tags=["CRM opportunity catalog"])


class OpportunityCatalogItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_item_id: UUID
    expected_catalog_version: int = Field(ge=1)


def _json(row: CRMOpportunityCatalogItem) -> dict:
    return {
        "id": row.id, "opportunity_id": row.opportunity_id,
        "catalog_item_id": row.catalog_item_id,
        "catalog_item_version": row.catalog_item_version,
        "code": row.item_code_snapshot, "name": row.item_name_snapshot,
        "item_type": row.item_type_snapshot, "category": row.category_snapshot,
        "created_at": row.created_at,
    }


async def _opportunity(
    context: TenantSessionContext, opportunity_id: UUID, permission: str, *, lock: bool = False,
) -> CRMOpportunity:
    statement = select(CRMOpportunity).where(
        CRMOpportunity.tenant_id == context.access.tenant_id,
        CRMOpportunity.id == opportunity_id,
    )
    if lock:
        statement = statement.with_for_update()
    opportunity = await context.session.scalar(statement)
    if opportunity is None or not await has_crm_permission(
        context, permission_key=permission, organization_unit_id=opportunity.organization_unit_id,
    ):
        raise HTTPException(status_code=404, detail="CRM opportunity scope not found")
    return opportunity


@router.get("", operation_id="listCRMOpportunityCatalogItems")
async def list_opportunity_catalog_items(
    opportunity_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    await _opportunity(context, opportunity_id, "crm.opportunity:view")
    rows = await context.session.scalars(select(CRMOpportunityCatalogItem).where(
        CRMOpportunityCatalogItem.tenant_id == context.access.tenant_id,
        CRMOpportunityCatalogItem.opportunity_id == opportunity_id,
    ).order_by(CRMOpportunityCatalogItem.created_at, CRMOpportunityCatalogItem.id))
    return {"items": [_json(row) for row in rows]}


@router.post("", status_code=201, operation_id="attachCRMOpportunityCatalogItem")
async def attach_opportunity_catalog_item(
    opportunity_id: UUID,
    payload: OpportunityCatalogItemCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    opportunity = await _opportunity(context, opportunity_id, "crm.opportunity:update", lock=True)
    if not await has_crm_permission(
        context, permission_key="crm.catalog:view", organization_unit_id=opportunity.organization_unit_id,
    ):
        raise HTTPException(status_code=404, detail="CRM opportunity scope not found")
    item = await context.session.scalar(select(CRMProductCatalogItem).where(
        CRMProductCatalogItem.tenant_id == context.access.tenant_id,
        CRMProductCatalogItem.id == payload.catalog_item_id,
    ).with_for_update())
    if item is None or item.organization_unit_id != opportunity.organization_unit_id:
        raise HTTPException(status_code=404, detail="Catalog item not found in opportunity organization")
    if not item.is_active:
        raise HTTPException(status_code=409, detail="Inactive catalog items cannot be attached")
    if item.version != payload.expected_catalog_version:
        raise HTTPException(status_code=409, detail="Catalog item version is stale")
    duplicate = await context.session.scalar(select(CRMOpportunityCatalogItem.id).where(
        CRMOpportunityCatalogItem.tenant_id == context.access.tenant_id,
        CRMOpportunityCatalogItem.opportunity_id == opportunity_id,
        CRMOpportunityCatalogItem.catalog_item_id == item.id,
    ))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Catalog item is already attached")
    row = CRMOpportunityCatalogItem(
        id=uuid4(), tenant_id=context.access.tenant_id, opportunity_id=opportunity.id,
        catalog_item_id=item.id, catalog_item_version=item.version,
        item_code_snapshot=item.code, item_name_snapshot=item.name,
        item_type_snapshot=item.item_type, category_snapshot=item.category,
        created_by_membership_id=context.access.membership_id,
    )
    context.session.add(row)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_opportunity.catalog_item_attached",
        target_type="crm_opportunity", target_key=str(opportunity.id),
        organization_unit_id=opportunity.organization_unit_id, before_state=None,
        after_state={"catalog_item_id": str(item.id), "catalog_item_version": item.version,
                     "code": item.code, "name": item.name}, correlation_id=None,
    ))
    await context.session.flush()
    return _json(row)
