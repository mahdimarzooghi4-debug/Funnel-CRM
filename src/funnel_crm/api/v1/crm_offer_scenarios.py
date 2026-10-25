"""Assumption-based, non-binding economic scenarios for marketing offers."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent, CRMMarketingOfferPlan, CRMMarketingOfferScenario,
    CRMProductCatalogItem, CRMProductCatalogPriceVersion,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/offer-plans/{plan_id}/scenarios", tags=["CRM marketing offer scenarios"])


class OfferScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    audience_size: int = Field(ge=0, le=1_000_000_000)
    expected_use_rate: Decimal = Field(ge=0, le=100, max_digits=6, decimal_places=3)
    price_version: int | None = Field(default=None, ge=1)
    offer_value_per_use: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    campaign_budget_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    campaign_budget_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    assumptions: str = Field(min_length=1, max_length=4000)

    @field_validator("name", "assumptions")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must contain a non-whitespace character")
        return value

    @model_validator(mode="after")
    def validate_pairs(self):
        if (self.price_version is None) != (self.offer_value_per_use is None):
            raise ValueError("select a catalog price and enter an offer value together")
        if (self.campaign_budget_amount is None) != (self.campaign_budget_currency is None):
            raise ValueError("campaign budget amount and currency must be provided together")
        return self


def _scenario_json(row: CRMMarketingOfferScenario) -> dict:
    uses = Decimal(row.audience_size) * row.expected_use_rate / Decimal(100)
    gross = uses * row.unit_amount if row.unit_amount is not None else None
    offer_value = uses * row.offer_value_per_use if row.offer_value_per_use is not None else None
    revenue_after_offer = gross - offer_value if gross is not None and offer_value is not None else None
    combined = None
    if revenue_after_offer is not None and row.campaign_budget_amount is not None:
        if row.currency == row.campaign_budget_currency:
            combined = revenue_after_offer - row.campaign_budget_amount
    return {
        "id": row.id, "offer_plan_id": row.offer_plan_id, "plan_version": row.plan_version,
        "name": row.name, "audience_size": row.audience_size,
        "expected_use_rate": str(row.expected_use_rate), "expected_uses": str(uses),
        "catalog_item_id": row.catalog_item_id, "catalog_item_version": row.catalog_item_version,
        "price_version": row.price_version, "unit_amount": str(row.unit_amount) if row.unit_amount is not None else None,
        "offer_value_per_use": str(row.offer_value_per_use) if row.offer_value_per_use is not None else None,
        "currency": row.currency,
        "gross_reference_revenue": str(gross) if gross is not None else None,
        "planned_offer_value": str(offer_value) if offer_value is not None else None,
        "revenue_after_offer": str(revenue_after_offer) if revenue_after_offer is not None else None,
        "campaign_budget_amount": str(row.campaign_budget_amount) if row.campaign_budget_amount is not None else None,
        "campaign_budget_currency": row.campaign_budget_currency,
        "revenue_after_offer_and_campaign_budget": str(combined) if combined is not None else None,
        "economic_completeness": "reference_price_missing" if row.unit_amount is None else "revenue_only_cost_missing",
        "margin_estimate": None,
        "margin_note": "هزینهٔ معتبر محصول یا خدمت ثبت نشده است؛ حاشیهٔ سود محاسبه نمی‌شود.",
        "assumptions": row.assumptions, "created_at": row.created_at,
    }


async def _authorized_plan(context: TenantSessionContext, plan_id: UUID, permission: str) -> CRMMarketingOfferPlan:
    plan = await context.session.scalar(select(CRMMarketingOfferPlan).where(
        CRMMarketingOfferPlan.tenant_id == context.access.tenant_id,
        CRMMarketingOfferPlan.id == plan_id,
    ).with_for_update() if permission == "crm.offer_plan:scenario" else select(CRMMarketingOfferPlan).where(
        CRMMarketingOfferPlan.tenant_id == context.access.tenant_id,
        CRMMarketingOfferPlan.id == plan_id,
    ))
    if plan is None or not await has_crm_permission(
        context, permission_key=permission, organization_unit_id=plan.organization_unit_id,
    ):
        raise HTTPException(status_code=404, detail="CRM offer plan scope not found")
    return plan


@router.get("", operation_id="listCRMMarketingOfferScenarios")
async def list_offer_scenarios(plan_id: UUID,
                               context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    await _authorized_plan(context, plan_id, "crm.offer_plan:view")
    rows = (await context.session.scalars(select(CRMMarketingOfferScenario).where(
        CRMMarketingOfferScenario.tenant_id == context.access.tenant_id,
        CRMMarketingOfferScenario.offer_plan_id == plan_id,
    ).order_by(CRMMarketingOfferScenario.created_at, CRMMarketingOfferScenario.id))).all()
    return {"items": [_scenario_json(row) for row in rows]}


@router.post("", status_code=201, operation_id="createCRMMarketingOfferScenario")
async def create_offer_scenario(plan_id: UUID, payload: OfferScenarioCreate,
                               context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    plan = await _authorized_plan(context, plan_id, "crm.offer_plan:scenario")
    if plan.status != "draft":
        raise HTTPException(status_code=409, detail="Scenarios can only be added before plan approval")
    if not await has_crm_permission(
        context, permission_key="crm.catalog:view", organization_unit_id=plan.organization_unit_id,
    ) and payload.price_version is not None:
        raise HTTPException(status_code=404, detail="CRM offer plan scope not found")

    item_version = 1
    unit_amount = currency = None
    if payload.price_version is not None:
        if plan.catalog_item_id is None:
            raise HTTPException(status_code=409, detail="Link a catalog item to the plan before using a catalog price")
        item = await context.session.scalar(select(CRMProductCatalogItem).where(
            CRMProductCatalogItem.tenant_id == context.access.tenant_id,
            CRMProductCatalogItem.id == plan.catalog_item_id,
        ))
        if item is None or item.organization_unit_id != plan.organization_unit_id or not item.is_active:
            raise HTTPException(status_code=409, detail="The plan catalog item is unavailable for scenario pricing")
        price = await context.session.get(
            CRMProductCatalogPriceVersion,
            (context.access.tenant_id, item.id, payload.price_version),
        )
        if price is None:
            raise HTTPException(status_code=404, detail="Catalog price version not found")
        planned_date = (plan.starts_at.astimezone(timezone.utc).date()
                        if plan.starts_at is not None else datetime.now(timezone.utc).date())
        if ((price.effective_start is not None and price.effective_start > planned_date)
                or (price.effective_end is not None and price.effective_end < planned_date)):
            raise HTTPException(status_code=409, detail="Catalog price is not effective for the plan start date")
        if payload.offer_value_per_use is not None and payload.offer_value_per_use > price.amount:
            raise HTTPException(status_code=422, detail="Offer value cannot exceed the reference unit price")
        item_version = item.version
        unit_amount, currency = price.amount, price.currency

    if (payload.campaign_budget_amount is not None and currency is not None
            and payload.campaign_budget_currency != currency):
        raise HTTPException(status_code=422, detail="Budget and catalog price currencies must match for combined comparison")

    row = CRMMarketingOfferScenario(
        id=uuid4(), tenant_id=context.access.tenant_id, offer_plan_id=plan.id,
        plan_version=plan.version, name=payload.name, audience_size=payload.audience_size,
        expected_use_rate=payload.expected_use_rate, catalog_item_id=plan.catalog_item_id,
        catalog_item_version=item_version, price_version=payload.price_version,
        unit_amount=unit_amount, offer_value_per_use=payload.offer_value_per_use,
        currency=currency, campaign_budget_amount=payload.campaign_budget_amount,
        campaign_budget_currency=payload.campaign_budget_currency, assumptions=payload.assumptions,
        created_by_membership_id=context.access.membership_id,
    )
    context.session.add(row)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id, action_key="crm_marketing_offer_scenario.created",
        target_type="crm_marketing_offer_plan", target_key=str(plan.id),
        organization_unit_id=plan.organization_unit_id, before_state=None,
        after_state={"scenario_id": str(row.id), "plan_version": plan.version,
                     "price_version": payload.price_version, "name": payload.name}, correlation_id=None,
    ))
    await context.session.flush()
    return _scenario_json(row)
