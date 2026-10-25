"""Organization-scoped marketing offer planning drafts."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent, CRMMarketingCampaign, CRMMarketingOfferPlan, CRMProductCatalogItem,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/offer-plans", tags=["CRM marketing offer plans"])


class OfferPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_unit_id: UUID
    name: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=2000)
    offer_type: str = Field(min_length=1, max_length=80)
    catalog_item_id: UUID | None = None
    audience_description: str = Field(min_length=1, max_length=1000)
    channel: str = Field(min_length=1, max_length=80)
    location_scope: str | None = Field(default=None, max_length=250)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    eligibility_conditions: str | None = Field(default=None, max_length=4000)
    success_metric: str = Field(min_length=1, max_length=500)
    campaign_id: UUID | None = None

    @field_validator("name", "objective", "offer_type", "audience_description", "channel", "success_metric")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must contain a non-whitespace character")
        return value

    @field_validator("location_scope", "eligibility_conditions")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("schedule timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def check_schedule(self):
        if self.starts_at is not None and self.ends_at is not None and self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be earlier than ends_at")
        return self


class OfferPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    objective: str | None = Field(default=None, min_length=1, max_length=2000)
    offer_type: str | None = Field(default=None, min_length=1, max_length=80)
    catalog_item_id: UUID | None = None
    audience_description: str | None = Field(default=None, min_length=1, max_length=1000)
    channel: str | None = Field(default=None, min_length=1, max_length=80)
    location_scope: str | None = Field(default=None, max_length=250)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    eligibility_conditions: str | None = Field(default=None, max_length=4000)
    success_metric: str | None = Field(default=None, min_length=1, max_length=500)
    campaign_id: UUID | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("at least one field must be updated")
        for key in ("name", "objective", "offer_type", "audience_description", "channel", "success_metric"):
            if key in self.model_fields_set and (getattr(self, key) is None or not getattr(self, key).strip()):
                raise ValueError(f"{key} cannot be blank")
        for key in ("starts_at", "ends_at"):
            value = getattr(self, key)
            if key in self.model_fields_set and value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("schedule timestamps must include a timezone")
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be earlier than ends_at")
        return self


def _json(row: CRMMarketingOfferPlan) -> dict:
    return {
        "id": row.id, "organization_unit_id": row.organization_unit_id,
        "name": row.name, "objective": row.objective, "offer_type": row.offer_type,
        "catalog_item_id": row.catalog_item_id, "audience_description": row.audience_description,
        "channel": row.channel, "location_scope": row.location_scope,
        "starts_at": row.starts_at, "ends_at": row.ends_at,
        "eligibility_conditions": row.eligibility_conditions, "success_metric": row.success_metric,
        "campaign_id": row.campaign_id, "status": row.status, "version": row.version,
        "owner_membership_id": row.owner_membership_id,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


async def _related_refs(context: TenantSessionContext, organization_unit_id: UUID,
                        catalog_item_id: UUID | None, campaign_id: UUID | None) -> None:
    if catalog_item_id is not None:
        item = await context.session.scalar(select(CRMProductCatalogItem).where(
            CRMProductCatalogItem.tenant_id == context.access.tenant_id,
            CRMProductCatalogItem.id == catalog_item_id,
        ))
        if item is None or item.organization_unit_id != organization_unit_id:
            raise HTTPException(status_code=404, detail="Catalog item not found in offer plan organization")
        if not item.is_active:
            raise HTTPException(status_code=409, detail="Inactive catalog items cannot be planned")
        if not await has_crm_permission(context, permission_key="crm.catalog:view", organization_unit_id=organization_unit_id):
            raise HTTPException(status_code=404, detail="CRM offer plan scope not found")
    if campaign_id is not None:
        campaign = await context.session.scalar(select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
            CRMMarketingCampaign.organization_unit_id == organization_unit_id,
        ))
        if campaign is None or not await has_crm_permission(
            context, permission_key="crm.campaign:view", organization_unit_id=organization_unit_id,
        ):
            raise HTTPException(status_code=404, detail="Campaign not found in offer plan organization")


@router.get("", operation_id="listCRMMarketingOfferPlans")
async def list_offer_plans(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = Query(default=None),
) -> dict:
    scopes = crm_scope_ids(context, permission_key="crm.offer_plan:view", cte_name="crm_offer_plan_scope")
    filters = [CRMMarketingOfferPlan.tenant_id == context.access.tenant_id,
               CRMMarketingOfferPlan.organization_unit_id.in_(scopes)]
    if organization_unit_id is not None:
        if not await has_crm_permission(context, permission_key="crm.offer_plan:view",
                                        organization_unit_id=organization_unit_id):
            raise HTTPException(status_code=404, detail="CRM offer plan scope not found")
        filters.append(CRMMarketingOfferPlan.organization_unit_id == organization_unit_id)
    rows = (await context.session.scalars(select(CRMMarketingOfferPlan).where(*filters)
        .order_by(CRMMarketingOfferPlan.updated_at.desc(), CRMMarketingOfferPlan.id).limit(100))).all()
    return {"items": [_json(row) for row in rows]}


@router.post("", status_code=201, operation_id="createCRMMarketingOfferPlan")
async def create_offer_plan(payload: OfferPlanCreate,
                            context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    if not await has_crm_permission(context, permission_key="crm.offer_plan:create",
                                    organization_unit_id=payload.organization_unit_id):
        raise HTTPException(status_code=404, detail="CRM offer plan scope not found")
    await _related_refs(context, payload.organization_unit_id, payload.catalog_item_id, payload.campaign_id)
    row = CRMMarketingOfferPlan(
        id=uuid4(), tenant_id=context.access.tenant_id, owner_membership_id=context.access.membership_id,
        status="draft", version=1, **payload.model_dump(),
    )
    context.session.add(row)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id, action_key="crm_marketing_offer_plan.created",
        target_type="crm_marketing_offer_plan", target_key=str(row.id),
        organization_unit_id=payload.organization_unit_id, before_state=None,
        after_state={"status": "draft", "version": 1, "name": payload.name}, correlation_id=None,
    ))
    await context.session.flush()
    return _json(row)


@router.patch("/{plan_id}", operation_id="updateCRMMarketingOfferPlan")
async def update_offer_plan(plan_id: UUID, payload: OfferPlanUpdate,
                            context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    row = await context.session.scalar(select(CRMMarketingOfferPlan).where(
        CRMMarketingOfferPlan.tenant_id == context.access.tenant_id,
        CRMMarketingOfferPlan.id == plan_id,
    ).with_for_update())
    if row is None or not await has_crm_permission(context, permission_key="crm.offer_plan:update",
                                                   organization_unit_id=row.organization_unit_id):
        raise HTTPException(status_code=404, detail="CRM offer plan scope not found")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Offer plan version is stale")
    changes = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    merged = {field: getattr(row, field) for field in OfferPlanCreate.model_fields if field != "organization_unit_id"}
    merged.update(changes)
    normalized = OfferPlanCreate(organization_unit_id=row.organization_unit_id, **merged)
    await _related_refs(context, row.organization_unit_id, normalized.catalog_item_id, normalized.campaign_id)
    before = {"version": row.version, "name": row.name, "status": row.status}
    for field, value in normalized.model_dump(exclude={"organization_unit_id"}).items():
        setattr(row, field, value)
    row.version += 1
    row.updated_at = datetime.now(timezone.utc)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id, action_key="crm_marketing_offer_plan.updated",
        target_type="crm_marketing_offer_plan", target_key=str(row.id),
        organization_unit_id=row.organization_unit_id, before_state=before,
        after_state={"version": row.version, "name": row.name, "status": row.status,
                     "changed_fields": sorted(changes)}, correlation_id=None,
    ))
    await context.session.flush()
    return _json(row)
