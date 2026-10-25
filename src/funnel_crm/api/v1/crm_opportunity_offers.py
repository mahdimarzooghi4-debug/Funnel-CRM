"""Non-binding offer drafts built from explicitly selected catalog prices."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent, CRMOpportunity, CRMOpportunityCatalogItem,
    CRMOpportunityOfferDraft, CRMOpportunityOfferDraftLine,
    CRMProductCatalogItem, CRMProductCatalogPriceVersion,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/opportunities/{opportunity_id}/offer-drafts", tags=["CRM sales offer drafts"])


class OfferDraftLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_item_id: UUID
    expected_catalog_version: int = Field(ge=1)
    price_version: int = Field(ge=1)
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class OfferDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[OfferDraftLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_catalog_items(self):
        ids = [line.catalog_item_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("each catalog item can appear once in an offer draft")
        return self


def _line_json(line: CRMOpportunityOfferDraftLine) -> dict:
    line_total = line.quantity * line.unit_amount
    return {
        "line_number": line.line_number, "catalog_item_id": line.catalog_item_id,
        "catalog_item_version": line.catalog_item_version,
        "price_version": line.catalog_price_version,
        "code": line.item_code_snapshot, "name": line.item_name_snapshot,
        "quantity": str(line.quantity), "unit_amount": str(line.unit_amount),
        "currency": line.currency, "line_total": str(line_total),
    }


async def _authorized_opportunity(
    context: TenantSessionContext, opportunity_id: UUID, permission: str,
) -> CRMOpportunity:
    opportunity = await context.session.scalar(select(CRMOpportunity).where(
        CRMOpportunity.tenant_id == context.access.tenant_id,
        CRMOpportunity.id == opportunity_id,
    ).with_for_update())
    if opportunity is None or not await has_crm_permission(
        context, permission_key=permission,
        organization_unit_id=opportunity.organization_unit_id,
    ):
        raise HTTPException(status_code=404, detail="CRM opportunity scope not found")
    return opportunity


async def _offer_json(context: TenantSessionContext, offer: CRMOpportunityOfferDraft) -> dict:
    lines = (await context.session.scalars(select(CRMOpportunityOfferDraftLine).where(
        CRMOpportunityOfferDraftLine.tenant_id == context.access.tenant_id,
        CRMOpportunityOfferDraftLine.offer_id == offer.id,
    ).order_by(CRMOpportunityOfferDraftLine.line_number))).all()
    totals: dict[str, Decimal] = {}
    for line in lines:
        totals[line.currency] = totals.get(line.currency, Decimal(0)) + line.quantity * line.unit_amount
    return {
        "id": offer.id, "opportunity_id": offer.opportunity_id,
        "status": offer.status, "created_at": offer.created_at,
        "lines": [_line_json(line) for line in lines],
        "totals_by_currency": {currency: str(amount) for currency, amount in sorted(totals.items())},
    }


@router.post("", status_code=201, operation_id="createCRMOpportunityOfferDraft")
async def create_offer_draft(
    opportunity_id: UUID,
    payload: OfferDraftCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    opportunity = await _authorized_opportunity(context, opportunity_id, "crm.offer:create")
    if not await has_crm_permission(
        context, permission_key="crm.catalog:view",
        organization_unit_id=opportunity.organization_unit_id,
    ):
        raise HTTPException(status_code=404, detail="CRM opportunity scope not found")
    offer_id = uuid4()
    rows: list[CRMOpportunityOfferDraftLine] = []
    today = datetime.now(timezone.utc).date()
    for number, request_line in enumerate(payload.lines, start=1):
        item = await context.session.scalar(select(CRMProductCatalogItem).where(
            CRMProductCatalogItem.tenant_id == context.access.tenant_id,
            CRMProductCatalogItem.id == request_line.catalog_item_id,
        ).with_for_update())
        if item is None or item.organization_unit_id != opportunity.organization_unit_id:
            raise HTTPException(status_code=404, detail="Catalog item not found in opportunity organization")
        if not item.is_active:
            raise HTTPException(status_code=409, detail="Inactive catalog items cannot be quoted")
        if item.version != request_line.expected_catalog_version:
            raise HTTPException(status_code=409, detail="Catalog item version is stale")
        attached = await context.session.scalar(select(CRMOpportunityCatalogItem.id).where(
            CRMOpportunityCatalogItem.tenant_id == context.access.tenant_id,
            CRMOpportunityCatalogItem.opportunity_id == opportunity.id,
            CRMOpportunityCatalogItem.catalog_item_id == item.id,
        ))
        if attached is None:
            raise HTTPException(status_code=409, detail="Catalog item must be linked to the opportunity first")
        price = await context.session.get(
            CRMProductCatalogPriceVersion,
            (context.access.tenant_id, item.id, request_line.price_version),
        )
        if price is None:
            raise HTTPException(status_code=404, detail="Catalog price version not found")
        if ((price.effective_start is not None and price.effective_start > today)
                or (price.effective_end is not None and price.effective_end < today)):
            raise HTTPException(status_code=409, detail="Selected catalog price is not currently effective")
        rows.append(CRMOpportunityOfferDraftLine(
            tenant_id=context.access.tenant_id, offer_id=offer_id, line_number=number,
            catalog_item_id=item.id, catalog_item_version=item.version,
            catalog_price_version=price.version, item_code_snapshot=item.code,
            item_name_snapshot=item.name, quantity=request_line.quantity,
            unit_amount=price.amount, currency=price.currency,
        ))
    offer = CRMOpportunityOfferDraft(
        id=offer_id, tenant_id=context.access.tenant_id,
        opportunity_id=opportunity.id, status="draft",
        created_by_membership_id=context.access.membership_id,
    )
    context.session.add(offer)
    context.session.add_all(rows)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_opportunity.offer_draft_created",
        target_type="crm_opportunity_offer_draft", target_key=str(offer.id),
        organization_unit_id=opportunity.organization_unit_id, before_state=None,
        after_state={"opportunity_id": str(opportunity.id), "line_count": len(rows), "status": "draft"},
        correlation_id=None,
    ))
    await context.session.flush()
    return await _offer_json(context, offer)


@router.get("", operation_id="listCRMOpportunityOfferDrafts")
async def list_offer_drafts(
    opportunity_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    await _authorized_opportunity(context, opportunity_id, "crm.offer:view")
    offers = (await context.session.scalars(select(CRMOpportunityOfferDraft).where(
        CRMOpportunityOfferDraft.tenant_id == context.access.tenant_id,
        CRMOpportunityOfferDraft.opportunity_id == opportunity_id,
    ).order_by(CRMOpportunityOfferDraft.created_at.desc(), CRMOpportunityOfferDraft.id))).all()
    return {"items": [await _offer_json(context, offer) for offer in offers]}
