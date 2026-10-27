"""Compare campaign-reported spend with explicitly campaign-linked commerce outcomes."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, tuple_

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMProductCommerceEvent,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/campaign-commerce-efficiency",
    tags=["CRM campaign commerce efficiency"],
)

ASSOCIATION_BASIS = (
    "Commerce outcomes are included only when the source event explicitly carries "
    "this CRM campaign ID. This observed association does not establish causation "
    "or accounting revenue attribution."
)


class CampaignCommerceCurrencyMetric(BaseModel):
    currency: str
    spend_amount: Decimal | None
    spend_observed_days: int
    paid_event_count: int
    paid_order_count: int
    paid_amount: Decimal
    net_paid_amount: Decimal
    net_paid_amount_per_paid_order: Decimal | None
    refund_event_count: int
    refunded_order_count: int
    refunded_amount: Decimal
    observed_paid_to_spend_multiple: Decimal | None
    observed_net_paid_to_spend_multiple: Decimal | None
    observed_refunds_to_spend_multiple: Decimal | None


class CampaignCommerceItem(BaseModel):
    campaign_id: UUID
    campaign_name: str
    channel: str
    objective_key: str
    currency_metrics: list[CampaignCommerceCurrencyMetric]


class CampaignCommerceEfficiencyReport(BaseModel):
    period_start: date
    period_end: date
    organization_unit_id: UUID | None
    generated_at: datetime
    association_basis: str
    currency_conversion_applied: bool
    causal_attribution_applied: bool
    total_campaign_count: int
    has_more_campaigns: bool
    campaigns: list[CampaignCommerceItem]


def _multiple(amount: Decimal, spend: Decimal | None) -> Decimal | None:
    if spend is None or spend <= 0:
        return None
    return (amount / spend).quantize(Decimal("0.000001"))


def _empty_item_state() -> dict[str, dict[str, object]]:
    return {}


@router.get(
    "",
    response_model=CampaignCommerceEfficiencyReport,
    operation_id="getCRMCampaignCommerceEfficiency",
)
async def get_campaign_commerce_efficiency(
    period_start: date = Query(...),
    period_end: date = Query(...),
    organization_unit_id: UUID | None = None,
    campaign_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignCommerceEfficiencyReport:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Reports are limited to 366 calendar days")

    campaign_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.campaign:view")
    )).all())
    commerce_units = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.commerce_event:view")
    )).all())
    allowed_units = sorted(campaign_units & commerce_units, key=str)
    if organization_unit_id is not None:
        if organization_unit_id not in allowed_units:
            raise HTTPException(
                status_code=403,
                detail="Campaign commerce report is not authorized for this organization scope",
            )
        allowed_units = [organization_unit_id]

    if not allowed_units:
        return CampaignCommerceEfficiencyReport(
            period_start=period_start,
            period_end=period_end,
            organization_unit_id=organization_unit_id,
            generated_at=datetime.now(timezone.utc),
            association_basis=ASSOCIATION_BASIS,
            currency_conversion_applied=False,
            causal_attribution_applied=False,
            total_campaign_count=0,
            has_more_campaigns=False,
            campaigns=[],
        )

    filters = [
        CRMMarketingCampaign.tenant_id == context.access.tenant_id,
        CRMMarketingCampaign.organization_unit_id.in_(allowed_units),
    ]
    if campaign_id is not None:
        filters.append(CRMMarketingCampaign.id == campaign_id)

    total_campaign_count = int(await context.session.scalar(
        select(func.count(CRMMarketingCampaign.id)).where(*filters)
    ) or 0)
    campaigns = (await context.session.scalars(
        select(CRMMarketingCampaign)
        .where(*filters)
        .order_by(CRMMarketingCampaign.name, CRMMarketingCampaign.id)
        .limit(limit)
        .offset(offset)
    )).all()
    if campaign_id is not None and total_campaign_count == 0:
        raise HTTPException(status_code=404, detail="Campaign not found in authorized scope")

    campaign_ids = [campaign.id for campaign in campaigns]
    spend_by_campaign: dict[UUID, dict[str, tuple[Decimal, int]]] = {
        campaign_id: {} for campaign_id in campaign_ids
    }
    commerce_by_campaign: dict[UUID, dict[str, dict[str, object]]] = {
        campaign_id: _empty_item_state() for campaign_id in campaign_ids
    }

    if campaign_ids:
        spend_start = period_start
        spend_end = period_end
        spend_rows = (await context.session.execute(
            select(
                CRMMarketingCampaignMeasurement.campaign_id,
                CRMMarketingCampaignMeasurement.actual_spend_currency,
                func.sum(CRMMarketingCampaignMeasurement.actual_spend_amount).label("spend_amount"),
                func.count(func.distinct(CRMMarketingCampaignMeasurement.measured_on)).label("observed_days"),
            )
            .where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id.in_(allowed_units),
                CRMMarketingCampaignMeasurement.campaign_id.in_(campaign_ids),
                CRMMarketingCampaignMeasurement.measured_on >= spend_start,
                CRMMarketingCampaignMeasurement.measured_on <= spend_end,
                CRMMarketingCampaignMeasurement.actual_spend_amount.is_not(None),
                CRMMarketingCampaignMeasurement.actual_spend_currency.is_not(None),
            )
            .group_by(
                CRMMarketingCampaignMeasurement.campaign_id,
                CRMMarketingCampaignMeasurement.actual_spend_currency,
            )
        )).all()
        for row in spend_rows:
            spend_by_campaign[row.campaign_id][row.actual_spend_currency] = (
                row.spend_amount,
                int(row.observed_days),
            )

        start_at = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
        end_exclusive = datetime.combine(
            period_end + timedelta(days=1), time.min, tzinfo=timezone.utc
        )
        commerce_rows = (await context.session.execute(
            select(
                CRMProductCommerceEvent.campaign_id,
                CRMProductCommerceEvent.currency,
                CRMProductCommerceEvent.event_kind,
                func.count(CRMProductCommerceEvent.id).label("event_count"),
                func.count(func.distinct(tuple_(
                    CRMProductCommerceEvent.source_product,
                    CRMProductCommerceEvent.order_reference,
                ))).label("order_count"),
                func.sum(CRMProductCommerceEvent.amount).label("amount_total"),
            )
            .where(
                CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                CRMProductCommerceEvent.organization_unit_id.in_(allowed_units),
                CRMProductCommerceEvent.campaign_id.in_(campaign_ids),
                CRMProductCommerceEvent.occurred_at >= start_at,
                CRMProductCommerceEvent.occurred_at < end_exclusive,
            )
            .group_by(
                CRMProductCommerceEvent.campaign_id,
                CRMProductCommerceEvent.currency,
                CRMProductCommerceEvent.event_kind,
            )
        )).all()
        for row in commerce_rows:
            state = commerce_by_campaign[row.campaign_id].setdefault(
                row.currency,
                {
                    "paid_event_count": 0,
                    "paid_order_count": 0,
                    "paid_amount": Decimal("0"),
                    "refund_event_count": 0,
                    "refunded_order_count": 0,
                    "refunded_amount": Decimal("0"),
                },
            )
            if row.event_kind == "paid":
                state["paid_event_count"] = int(row.event_count)
                state["paid_order_count"] = int(row.order_count)
                state["paid_amount"] = row.amount_total or Decimal("0")
            else:
                state["refund_event_count"] = int(row.event_count)
                state["refunded_order_count"] = int(row.order_count)
                state["refunded_amount"] = row.amount_total or Decimal("0")

    items = []
    for campaign in campaigns:
        currencies = set(spend_by_campaign[campaign.id]) | set(commerce_by_campaign[campaign.id])
        metrics = []
        for currency in sorted(currencies):
            spend_info = spend_by_campaign[campaign.id].get(currency)
            spend = spend_info[0] if spend_info is not None else None
            state = commerce_by_campaign[campaign.id].get(currency, {})
            paid_amount = state.get("paid_amount", Decimal("0"))
            refunded_amount = state.get("refunded_amount", Decimal("0"))
            net_paid_amount = paid_amount - refunded_amount
            paid_order_count = state.get("paid_order_count", 0)
            metrics.append(CampaignCommerceCurrencyMetric(
                currency=currency,
                spend_amount=spend,
                spend_observed_days=spend_info[1] if spend_info is not None else 0,
                paid_event_count=state.get("paid_event_count", 0),
                paid_order_count=paid_order_count,
                paid_amount=paid_amount,
                net_paid_amount=net_paid_amount,
                net_paid_amount_per_paid_order=(
                    (net_paid_amount / Decimal(paid_order_count)).quantize(Decimal("0.000001"))
                    if paid_order_count else None
                ),
                refund_event_count=state.get("refund_event_count", 0),
                refunded_order_count=state.get("refunded_order_count", 0),
                refunded_amount=refunded_amount,
                observed_paid_to_spend_multiple=_multiple(paid_amount, spend),
                observed_net_paid_to_spend_multiple=_multiple(net_paid_amount, spend),
                observed_refunds_to_spend_multiple=_multiple(refunded_amount, spend),
            ))
        items.append(CampaignCommerceItem(
            campaign_id=campaign.id,
            campaign_name=campaign.name,
            channel=campaign.channel,
            objective_key=campaign.objective_key,
            currency_metrics=metrics,
        ))

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_campaign.commerce_efficiency_report_viewed",
        target_type="crm_campaign_commerce_efficiency_report",
        target_key=str(campaign_id or organization_unit_id or context.access.tenant_id),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "campaign_id": str(campaign_id) if campaign_id else None,
            "total_campaign_count": total_campaign_count,
            "returned_campaign_count": len(campaigns),
            "limit": limit,
            "offset": offset,
        },
        correlation_id=None,
    ))
    await context.session.flush()

    return CampaignCommerceEfficiencyReport(
        period_start=period_start,
        period_end=period_end,
        organization_unit_id=organization_unit_id,
        generated_at=datetime.now(timezone.utc),
        association_basis=ASSOCIATION_BASIS,
        currency_conversion_applied=False,
        causal_attribution_applied=False,
        total_campaign_count=total_campaign_count,
        has_more_campaigns=offset + len(campaigns) < total_campaign_count,
        campaigns=items,
    )
