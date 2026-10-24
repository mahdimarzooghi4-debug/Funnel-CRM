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


class OutcomeEfficiency(BaseModel):
    paired_campaign_days: int
    spend_amount: Decimal
    outcome_count: int
    cost_per_outcome: Decimal | None


class ReturnEfficiency(BaseModel):
    paired_campaign_days: int
    spend_amount: Decimal
    attributed_revenue_amount: Decimal
    return_multiple: Decimal | None


class CampaignEfficiency(BaseModel):
    cost_per_lead_by_currency: dict[str, OutcomeEfficiency]
    cost_per_conversion_by_currency: dict[str, OutcomeEfficiency]
    roas_by_currency: dict[str, ReturnEfficiency]


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
    efficiency: CampaignEfficiency


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
    efficiency: CampaignEfficiency


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


class ValueChange(BaseModel):
    current_value: Decimal | int | float | None
    comparison_value: Decimal | int | float | None
    absolute_change: Decimal | int | float | None
    percent_change: float | None
    comparable: bool


class PerformanceChange(BaseModel):
    campaign_count: ValueChange
    measurement_record_count: ValueChange
    observed_campaign_days: dict[str, ValueChange]
    totals: dict[str, ValueChange]
    rates: dict[str, ValueChange]
    actual_spend_by_currency: dict[str, ValueChange]
    attributed_revenue_by_currency: dict[str, ValueChange]
    cost_per_lead_by_currency: dict[str, ValueChange]
    cost_per_conversion_by_currency: dict[str, ValueChange]
    roas_by_currency: dict[str, ValueChange]


class AggregatePeriodComparison(BaseModel):
    current: PerformanceAggregate
    comparison: PerformanceAggregate
    change: PerformanceChange


class GroupPeriodComparison(BaseModel):
    key: str
    current: PerformanceAggregate | None
    comparison: PerformanceAggregate | None
    change: PerformanceChange


class CampaignPortfolioComparison(BaseModel):
    current_period_start: date
    current_period_end: date
    comparison_period_start: date
    comparison_period_end: date
    organization_unit_id: UUID | None
    grouped_by: Literal["channel", "objective"]
    total: AggregatePeriodComparison
    groups: list[GroupPeriodComparison]


def _rate(numerator: int, denominator: int, paired_campaign_days: int) -> float | None:
    return round(100 * numerator / denominator, 4) if paired_campaign_days and denominator > 0 else None


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
        "efficiency": {
            "cost_per_lead": {},
            "cost_per_conversion": {},
            "roas": {},
        },
    }


def _add_money(target: dict[str, Decimal], currency: str | None, amount: Decimal | None) -> None:
    if currency is not None and amount is not None:
        target[currency] = target.get(currency, Decimal("0")) + amount


def _value_change(
    current: Decimal | int | float | None,
    comparison: Decimal | int | float | None,
) -> ValueChange:
    comparable = current is not None and comparison is not None
    difference = current - comparison if comparable else None
    percent = (
        round(float(difference) / abs(float(comparison)) * 100, 4)
        if comparable and comparison != 0
        else None
    )
    return ValueChange(
        current_value=current,
        comparison_value=comparison,
        absolute_change=difference,
        percent_change=percent,
        comparable=comparable,
    )


def _map_change(
    current: dict[str, Decimal | int | float],
    comparison: dict[str, Decimal | int | float],
) -> dict[str, ValueChange]:
    return {
        key: _value_change(current.get(key), comparison.get(key))
        for key in sorted(set(current) | set(comparison))
    }


def _performance_change(
    current: PerformanceAggregate | None,
    comparison: PerformanceAggregate | None,
) -> PerformanceChange:
    def efficiency_values(
        aggregate: PerformanceAggregate | None, attribute: str, value_attribute: str
    ) -> dict[str, Decimal | None]:
        if aggregate is None:
            return {}
        metrics = getattr(aggregate.efficiency, attribute)
        return {
            currency: getattr(metric, value_attribute)
            for currency, metric in metrics.items()
        }

    current_campaign_count = current.campaign_count if current is not None else None
    comparison_campaign_count = comparison.campaign_count if comparison is not None else None
    current_record_count = current.measurement_record_count if current is not None else None
    comparison_record_count = comparison.measurement_record_count if comparison is not None else None
    current_observed = current.observed_campaign_days if current is not None else {}
    comparison_observed = comparison.observed_campaign_days if comparison is not None else {}
    current_totals = current.totals if current is not None else {}
    comparison_totals = comparison.totals if comparison is not None else {}
    current_spend = current.actual_spend_by_currency if current is not None else {}
    comparison_spend = comparison.actual_spend_by_currency if comparison is not None else {}
    current_revenue = current.attributed_revenue_by_currency if current is not None else {}
    comparison_revenue = comparison.attributed_revenue_by_currency if comparison is not None else {}

    return PerformanceChange(
        campaign_count=_value_change(current_campaign_count, comparison_campaign_count),
        measurement_record_count=_value_change(current_record_count, comparison_record_count),
        observed_campaign_days=_map_change(current_observed, comparison_observed),
        totals=_map_change(current_totals, comparison_totals),
        rates={
            key: _value_change(
                getattr(current, key) if current is not None else None,
                getattr(comparison, key) if comparison is not None else None,
            )
            for key in (
                "click_through_rate_percent",
                "lead_rate_per_click_percent",
                "conversion_rate_per_click_percent",
            )
        },
        actual_spend_by_currency=_map_change(current_spend, comparison_spend),
        attributed_revenue_by_currency=_map_change(current_revenue, comparison_revenue),
        cost_per_lead_by_currency=_map_change(
            efficiency_values(current, "cost_per_lead_by_currency", "cost_per_outcome"),
            efficiency_values(comparison, "cost_per_lead_by_currency", "cost_per_outcome"),
        ),
        cost_per_conversion_by_currency=_map_change(
            efficiency_values(current, "cost_per_conversion_by_currency", "cost_per_outcome"),
            efficiency_values(comparison, "cost_per_conversion_by_currency", "cost_per_outcome"),
        ),
        roas_by_currency=_map_change(
            efficiency_values(current, "roas_by_currency", "return_multiple"),
            efficiency_values(comparison, "roas_by_currency", "return_multiple"),
        ),
    )


def _divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return (numerator / denominator).quantize(Decimal("0.000001")) if denominator > 0 else None


def _finish_efficiency(state: dict[str, object]) -> CampaignEfficiency:
    cost_per_lead = state["cost_per_lead"]
    cost_per_conversion = state["cost_per_conversion"]
    roas = state["roas"]
    return CampaignEfficiency(
        cost_per_lead_by_currency={
            currency: OutcomeEfficiency(
                paired_campaign_days=values[2],
                spend_amount=values[0],
                outcome_count=values[1],
                cost_per_outcome=_divide(values[0], Decimal(values[1])),
            )
            for currency, values in cost_per_lead.items()
        },
        cost_per_conversion_by_currency={
            currency: OutcomeEfficiency(
                paired_campaign_days=values[2],
                spend_amount=values[0],
                outcome_count=values[1],
                cost_per_outcome=_divide(values[0], Decimal(values[1])),
            )
            for currency, values in cost_per_conversion.items()
        },
        roas_by_currency={
            currency: ReturnEfficiency(
                paired_campaign_days=values[2],
                spend_amount=values[0],
                attributed_revenue_amount=values[1],
                return_multiple=_divide(values[1], values[0]),
            )
            for currency, values in roas.items()
        },
    )


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
        efficiency=_finish_efficiency(acc["efficiency"]),
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

    measured = CRMMarketingCampaignMeasurement
    spend_present = measured.actual_spend_amount.is_not(None)
    lead_pair = and_(spend_present, measured.leads.is_not(None))
    conversion_pair = and_(spend_present, measured.conversions.is_not(None))
    same_currency_roas_pair = and_(
        spend_present,
        measured.attributed_revenue_amount.is_not(None),
        measured.actual_spend_currency == measured.attributed_revenue_currency,
    )
    efficiency_query = select(
        CRMMarketingCampaign.id.label("campaign_id"),
        measured.actual_spend_currency.label("currency"),
        func.sum(case((lead_pair, measured.actual_spend_amount), else_=0)).label("lead_spend"),
        func.sum(case((lead_pair, measured.leads), else_=0)).label("lead_count"),
        func.count(case((lead_pair, 1), else_=None)).label("lead_days"),
        func.sum(case((conversion_pair, measured.actual_spend_amount), else_=0)).label("conversion_spend"),
        func.sum(case((conversion_pair, measured.conversions), else_=0)).label("conversion_count"),
        func.count(case((conversion_pair, 1), else_=None)).label("conversion_days"),
        func.sum(case((same_currency_roas_pair, measured.actual_spend_amount), else_=0)).label("roas_spend"),
        func.sum(case((same_currency_roas_pair, measured.attributed_revenue_amount), else_=0)).label("roas_revenue"),
        func.count(case((same_currency_roas_pair, 1), else_=None)).label("roas_days"),
    ).join(
        measured,
        (measured.tenant_id == CRMMarketingCampaign.tenant_id)
        & (measured.organization_unit_id == CRMMarketingCampaign.organization_unit_id)
        & (measured.campaign_id == CRMMarketingCampaign.id),
    ).where(
        CRMMarketingCampaign.tenant_id == context.access.tenant_id,
        CRMMarketingCampaign.organization_unit_id.in_(allowed_units),
        measured.tenant_id == context.access.tenant_id,
        measured.measured_on >= period_start,
        measured.measured_on <= period_end,
    )
    if organization_unit_id is not None:
        efficiency_query = efficiency_query.where(
            CRMMarketingCampaign.organization_unit_id == organization_unit_id
        )
    efficiency_rows = (await context.session.execute(
        efficiency_query.group_by(CRMMarketingCampaign.id, measured.actual_spend_currency)
    )).mappings().all()
    efficiency_by_campaign: dict[UUID, dict[str, dict[str, list[object]]]] = {}
    for row in efficiency_rows:
        currency = row["currency"]
        if currency is None:
            continue
        campaign_efficiency = efficiency_by_campaign.setdefault(
            row["campaign_id"],
            {"cost_per_lead": {}, "cost_per_conversion": {}, "roas": {}},
        )
        if row["lead_days"]:
            campaign_efficiency["cost_per_lead"][currency] = [
                row["lead_spend"], int(row["lead_count"]), int(row["lead_days"])
            ]
        if row["conversion_days"]:
            campaign_efficiency["cost_per_conversion"][currency] = [
                row["conversion_spend"], int(row["conversion_count"]), int(row["conversion_days"])
            ]
        if row["roas_days"]:
            campaign_efficiency["roas"][currency] = [
                row["roas_spend"], row["roas_revenue"], int(row["roas_days"])
            ]

    all_acc = _empty_accumulator()
    group_accs: dict[str, dict[str, object]] = {}
    items: list[tuple[dict[str, object], CampaignPerformanceItem]] = []
    sort_column = sort_by

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
            "totals": {key: int(row[f"total_{key}"]) if row[f"total_{key}"] is not None else None for key in METRICS},
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
            "efficiency": efficiency_by_campaign.get(
                campaign_id,
                {"cost_per_lead": {}, "cost_per_conversion": {}, "roas": {}},
            ),
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
            efficiency=_finish_efficiency(internal["efficiency"]),
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
    for metric, currency_values in item["efficiency"].items():
        for currency, values in currency_values.items():
            target = acc["efficiency"][metric].setdefault(
                currency,
                [Decimal("0"), 0, 0],
            )
            for index, value in enumerate(values):
                target[index] += value
    currency = item["planned_budget_currency"]
    amount = item["planned_budget_amount"]
    _add_money(acc["planned_budget_by_currency"], currency, amount)



@router.get(
    "/comparison",
    response_model=CampaignPortfolioComparison,
    operation_id="compareCampaignPortfolioPerformance",
)
async def compare_campaign_portfolio_performance(
    current_period_start: date = Query(...),
    current_period_end: date = Query(...),
    comparison_period_start: date = Query(...),
    comparison_period_end: date = Query(...),
    grouped_by: Literal["channel", "objective"] = Query(default="channel"),
    organization_unit_id: UUID | None = None,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignPortfolioComparison:
    periods = (
        (current_period_start, current_period_end),
        (comparison_period_start, comparison_period_end),
    )
    if any(start > end for start, end in periods):
        raise HTTPException(status_code=422, detail="Period start must not be after period end")
    if any((end - start).days > 365 for start, end in periods):
        raise HTTPException(status_code=422, detail="Performance reports are limited to 366 calendar days")
    if (current_period_end - current_period_start).days != (
        comparison_period_end - comparison_period_start
    ).days:
        raise HTTPException(status_code=422, detail="Comparison periods must have the same number of calendar days")
    overlaps = current_period_start <= comparison_period_end and comparison_period_start <= current_period_end
    if overlaps:
        raise HTTPException(status_code=422, detail="Comparison periods must not overlap")

    current_report = await get_campaign_portfolio_performance(
        period_start=current_period_start,
        period_end=current_period_end,
        grouped_by=grouped_by,
        organization_unit_id=organization_unit_id,
        sort_by="conversions",
        limit=1,
        offset=0,
        context=context,
    )
    comparison_report = await get_campaign_portfolio_performance(
        period_start=comparison_period_start,
        period_end=comparison_period_end,
        grouped_by=grouped_by,
        organization_unit_id=organization_unit_id,
        sort_by="conversions",
        limit=1,
        offset=0,
        context=context,
    )
    current_groups = {group.key: group.metrics for group in current_report.groups}
    comparison_groups = {group.key: group.metrics for group in comparison_report.groups}
    return CampaignPortfolioComparison(
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        comparison_period_start=comparison_period_start,
        comparison_period_end=comparison_period_end,
        organization_unit_id=organization_unit_id,
        grouped_by=grouped_by,
        total=AggregatePeriodComparison(
            current=current_report.totals,
            comparison=comparison_report.totals,
            change=_performance_change(current_report.totals, comparison_report.totals),
        ),
        groups=[
            GroupPeriodComparison(
                key=key,
                current=current_groups.get(key),
                comparison=comparison_groups.get(key),
                change=_performance_change(
                    current_groups.get(key),
                    comparison_groups.get(key),
                ),
            )
            for key in sorted(set(current_groups) | set(comparison_groups))
        ],
    )
