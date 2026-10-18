"""Portfolio-level reporting over recorded campaign measurements."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids
from funnel_crm.platform.models import CRMMarketingCampaign, CRMMarketingCampaignMeasurement
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/campaign-performance",
    tags=["CRM marketing analytics"],
)
METRICS = ("impressions", "reach", "clicks", "responses", "leads", "conversions")


class PerformanceAggregate(BaseModel):
    campaign_count: int
    measurement_record_count: int
    observed_campaign_days: dict[str, int]
    totals: dict[str, int | None]
    click_through_rate_percent: float | None
    lead_rate_per_click_percent: float | None
    conversion_rate_per_click_percent: float | None
    planned_budget_by_currency: dict[str, Decimal]
    actual_spend_by_currency: dict[str, Decimal]
    attributed_revenue_by_currency: dict[str, Decimal]


class CampaignPerformanceItem(BaseModel):
    campaign_id: UUID
    name: str
    organization_unit_id: UUID
    channel: str
    objective_key: str
    status: str
    measurement_record_count: int
    observed_campaign_days: dict[str, int]
    totals: dict[str, int | None]
    click_through_rate_percent: float | None
    lead_rate_per_click_percent: float | None
    conversion_rate_per_click_percent: float | None
    planned_budget_amount: Decimal | None
    planned_budget_currency: str | None
    actual_spend_by_currency: dict[str, Decimal]
    attributed_revenue_by_currency: dict[str, Decimal]


class PerformanceGroup(BaseModel):
    key: str
    metrics: PerformanceAggregate


class CampaignPortfolioPerformance(BaseModel):
    period_start: date
    period_end: date
    organization_unit_id: UUID | None
    grouped_by: Literal["channel", "objective"]
    totals: PerformanceAggregate
    groups: list[PerformanceGroup]
    campaigns: list[CampaignPerformanceItem]
    campaign_list_truncated: bool
    sort_by: Literal["conversions", "leads", "clicks"]


def _rate(numerator: int, denominator: int, paired_days: int) -> float | None:
    return round(100 * numerator / denominator, 4) if paired_days and denominator > 0 else None


def _empty_accumulator() -> dict[str, object]:
    return {
        "campaign_count": 0,
        "measurement_record_count": 0,
        "observed_campaign_days": {key: 0 for key in METRICS},
        "totals": {key: 0 for key in METRICS},
        "paired": {
            "clicks_impressions": [0, 0, 0],
            "leads_clicks": [0, 0, 0],
            "conversions_clicks": [0, 0, 0],
        },
        "planned_budget_by_currency": {},
        "actual_spend_by_currency": {},
        "attributed_revenue_by_currency": {},
    }


def _add_money(target: dict[str, Decimal], currency: str | None, amount: Decimal | None) -> None:
    if currency is not None and amount is not None:
        target[currency] = target.get(currency, Decimal("0")) + amount


def _finish(acc: dict[str, object]) -> PerformanceAggregate:
    totals = acc["totals"]
    coverage = acc["observed_campaign_days"]
    paired = acc["paired"]
    assert isinstance(totals, dict) and isinstance(coverage, dict) and isinstance(paired, dict)
    ci = paired["clicks_impressions"]
    lc = paired["leads_clicks"]
    vc = paired["conversions_clicks"]
    return PerformanceAggregate(
        campaign_count=acc["campaign_count"],
        measurement_record_count=acc["measurement_record_count"],
        observed_campaign_days=coverage,
        totals={key: totals[key] if coverage[key] else None for key in METRICS},
        click_through_rate_percent=_rate(ci[0], ci[1], ci[2]),
        lead_rate_per_click_percent=_rate(lc[0], lc[1], lc[2]),
        conversion_rate_per_click_percent=_rate(vc[0], vc[1], vc[2]),
        planned_budget_by_currency=acc["planned_budget_by_currency"],
        actual_spend_by_currency=acc["actual_spend_by_currency"],
        attributed_revenue_by_currency=acc["attributed_revenue_by_currency"],
    )


@router.get(
    "/portfolio",
    response_model=CampaignPortfolioPerformance,
    operation_id="getCampaignPortfolioPerformance",
)
async def get_campaign_portfolio_performance(
    period_start: date = Query(...),
    period_end: date = Query(...),
    grouped_by: Literal["channel", "objective"] = Query(default="channel"),
    organization_unit_id: UUID | None = None,
    sort_by: Literal["conversions", "leads", "clicks"] = Query(default="conversions"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignPortfolioPerformance:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Performance reports are limited to 366 calendar days")

    allowed_units = list(
        (await context.session.scalars(
            crm_scope_ids(context, permission_key="crm.campaign:view")
        )).all()
    )
    if organization_unit_id is not None and organization_unit_id not in allowed_units:
        raise HTTPException(status_code=403, detail="Campaign performance is not authorized for this organization scope")
    if not allowed_units:
        return CampaignPortfolioPerformance(
            period_start=period_start,
            period_end=period_end,
            organization_unit_id=organization_unit_id,
            grouped_by=grouped_by,
            totals=_finish(_empty_accumulator()),
            groups=[],
            campaigns=[],
            campaign_list_truncated=False,
            sort_by=sort_by,
        )

    filters = [
        CRMMarketingCampaign.tenant_id == context.access.tenant_id,
        CRMMarketingCampaign.organization_unit_id.in_(allowed_units),
        CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
        CRMMarketingCampaignMeasurement.measured_on >= period_start,
        CRMMarketingCampaignMeasurement.measured_on <= period_end,
    ]
    if organization_unit_id is not None:
        filters.append(CRMMarketingCampaign.organization_unit_id == organization_unit_id)

    metric_selects = []
    for key in METRICS:
        column = getattr(CRMMarketingCampaignMeasurement, key)
        metric_selects.extend(
            [
                func.sum(column).label(f"total_{key}"),
                func.count(column).label(f"days_{key}"),
            ]
        )
    pair_specs = {
        "clicks_impressions": ("clicks", "impressions"),
        "leads_clicks": ("leads", "clicks"),
        "conversions_clicks": ("conversions", "clicks"),
    }
    pair_selects = []
    for name, (numerator_key, denominator_key) in pair_specs.items():
        numerator = getattr(CRMMarketingCampaignMeasurement, numerator_key)
        denominator = getattr(CRMMarketingCampaignMeasurement, denominator_key)
        both = and_(numerator.is_not(None), denominator.is_not(None))
        pair_selects.extend(
            [
                func.sum(case((both, numerator), else_=None)).label(f"pair_{name}_numerator"),
                func.sum(case((both, denominator), else_=None)).label(f"pair_{name}_denominator"),
                func.count(case((both, 1), else_=None)).label(f"pair_{name}_days"),
            ]
        )

    aggregate_rows = (await context.session.execute(
        select(
            CRMMarketingCampaign.id.label("campaign_id"),
            CRMMarketingCampaign.name,
            CRMMarketingCampaign.organization_unit_id,
            CRMMarketingCampaign.channel,
            CRMMarketingCampaign.objective_key,
            CRMMarketingCampaign.status,
            CRMMarketingCampaign.planned_budget_amount,
            CRMMarketingCampaign.planned_budget_currency,
            func.count(CRMMarketingCampaignMeasurement.id).label("measurement_record_count"),
            *metric_selects,
            *pair_selects,
        )
        .join(
            CRMMarketingCampaignMeasurement,
            (CRMMarketingCampaignMeasurement.tenant_id == CRMMarketingCampaign.tenant_id)
            & (CRMMarketingCampaignMeasurement.organization_unit_id == CRMMarketingCampaign.organization_unit_id)
            & (CRMMarketingCampaignMeasurement.campaign_id == CRMMarketingCampaign.id),
        )
        .where(*filters)
        .group_by(
            CRMMarketingCampaign.id,
            CRMMarketingCampaign.name,
            CRMMarketingCampaign.organization_unit_id,
            CRMMarketingCampaign.channel,
            CRMMarketingCampaign.objective_key,
            CRMMarketingCampaign.status,
            CRMMarketingCampaign.planned_budget_amount,
            CRMMarketingCampaign.planned_budget_currency,
        )
    )).mappings().all()

    spend_rows = (await context.session.execute(
        select(
            CRMMarketingCampaignMeasurement.campaign_id,
            CRMMarketingCampaignMeasurement.actual_spend_currency,
            func.sum(CRMMarketingCampaignMeasurement.actual_spend_amount),
        )
        .where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.organization_unit_id.in_(allowed_units),
            CRMMarketingCampaignMeasurement.measured_on >= period_start,
            CRMMarketingCampaignMeasurement.measured_on <= period_end,
            CRMMarketingCampaignMeasurement.actual_spend_amount.is_not(None),
        )
        .group_by(
            CRMMarketingCampaignMeasurement.campaign_id,
            CRMMarketingCampaignMeasurement.actual_spend_currency,
        )
    )).all()
    revenue_rows = (await context.session.execute(
        select(
            CRMMarketingCampaignMeasurement.campaign_id,
            CRMMarketingCampaignMeasurement.attributed_revenue_currency,
            func.sum(CRMMarketingCampaignMeasurement.attributed_revenue_amount),
        )
        .where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.organization_unit_id.in_(allowed_units),
            CRMMarketingCampaignMeasurement.measured_on >= period_start,
            CRMMarketingCampaignMeasurement.measured_on <= period_end,
            CRMMarketingCampaignMeasurement.attributed_revenue_amount.is_not(None),
        )
        .group_by(
            CRMMarketingCampaignMeasurement.campaign_id,
            CRMMarketingCampaignMeasurement.attributed_revenue_currency,
        )
    )).all()

    money: dict[UUID, dict[str, dict[str, Decimal]]] = {}
    for campaign_id, currency, amount in spend_rows:
        money.setdefault(campaign_id, {"spend": {}, "revenue": {}})["spend"][currency] = amount
    for campaign_id, currency, amount in revenue_rows:
        money.setdefault(campaign_id, {"spend": {}, "revenue": {}})["revenue"][currency] = amount

    all_acc = _empty_accumulator()
    group_accs: dict[str, dict[str, object]] = {}
    items: list[tuple[dict[str, object], CampaignPerformanceItem]] = []
    sort_column = f"total_{sort_by}"

    for row in aggregate_rows:
        campaign_id = row["campaign_id"]
        currency_rows = money.get(campaign_id, {"spend": {}, "revenue": {}})
        internal: dict[str, object] = {
            "campaign_id": campaign_id,
            "name": row["name"],
            "organization_unit_id": row["organization_unit_id"],
            "channel": row["channel"],
            "objective_key": row["objective_key"],
            "status": row["status"],
            "planned_budget_amount": row["planned_budget_amount"],
            "planned_budget_currency": row["planned_budget_currency"],
            "measurement_record_count": int(row["measurement_record_count"]),
            "coverage": {key: int(row[f"days_{key}"] or 0) for key in METRICS},
            "totals": {key: row[f"total_{key}"] for key in METRICS},
            "pairs": {
                name: [
                    int(row[f"pair_{name}_numerator"] or 0),
                    int(row[f"pair_{name}_denominator"] or 0),
                    int(row[f"pair_{name}_days"] or 0),
                ]
                for name in pair_specs
            },
            "spend": currency_rows["spend"],
            "revenue": currency_rows["revenue"],
        }
        _accumulate(all_acc, internal)
        group_key = str(row["channel"] if grouped_by == "channel" else row["objective_key"])
        group_acc = group_accs.setdefault(group_key, _empty_accumulator())
        _accumulate(group_acc, internal)
        items.append((internal, CampaignPerformanceItem(
            campaign_id=campaign_id,
            name=row["name"],
            organization_unit_id=row["organization_unit_id"],
            channel=row["channel"],
            objective_key=row["objective_key"],
            status=row["status"],
            measurement_record_count=int(row["measurement_record_count"]),
            observed_campaign_days=internal["coverage"],
            totals=internal["totals"],
            click_through_rate_percent=_rate(*internal["pairs"]["clicks_impressions"]),
            lead_rate_per_click_percent=_rate(*internal["pairs"]["leads_clicks"]),
            conversion_rate_per_click_percent=_rate(*internal["pairs"]["conversions_clicks"]),
            planned_budget_amount=row["planned_budget_amount"],
            planned_budget_currency=row["planned_budget_currency"],
            actual_spend_by_currency=currency_rows["spend"],
            attributed_revenue_by_currency=currency_rows["revenue"],
        )))

    items.sort(
        key=lambda item: (
            -(item[0]["totals"].get(sort_column, 0) or 0),
            item[1].name.casefold(),
            str(item[1].campaign_id),
        )
    )
    selected = items[offset:offset + limit]
    return CampaignPortfolioPerformance(
        period_start=period_start,
        period_end=period_end,
        organization_unit_id=organization_unit_id,
        grouped_by=grouped_by,
        totals=_finish(all_acc),
        groups=[
            PerformanceGroup(key=key, metrics=_finish(group_accs[key]))
            for key in sorted(group_accs)
        ],
        campaigns=[item for _, item in selected],
        campaign_list_truncated=offset + limit < len(items),
        sort_by=sort_by,
    )


def _accumulate(acc: dict[str, object], item: dict[str, object]) -> None:
    acc["campaign_count"] += 1
    acc["measurement_record_count"] += item["measurement_record_count"]
    for key in METRICS:
        acc["observed_campaign_days"][key] += item["coverage"][key]
        value = item["totals"][key]
        if value is not None:
            acc["totals"][key] += value
    for key in item["pairs"]:
        for index, value in enumerate(item["pairs"][key]):
            acc["paired"][key][index] += value
    for currency, amount in item["spend"].items():
        _add_money(acc["actual_spend_by_currency"], currency, amount)
    for currency, amount in item["revenue"].items():
        _add_money(acc["attributed_revenue_by_currency"], currency, amount)
    currency = item["planned_budget_currency"]
    amount = item["planned_budget_amount"]
    _add_money(acc["planned_budget_by_currency"], currency, amount)
