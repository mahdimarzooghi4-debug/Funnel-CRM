"""Tenant- and organization-scoped planning scenarios for campaign budgets."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select

from funnel_crm.api.v1.crm_metric_catalog import MetricDefinition, get_metric_definition

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingBudgetScenario,
    CRMMarketingBudgetScenarioLine,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/budget-scenarios", tags=["CRM marketing budget scenarios"])


class BudgetAllocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    planned_budget_amount: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    planned_budget_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z][A-Z][A-Z]")


class BudgetScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    name: str = Field(min_length=1, max_length=160)
    allocations: list[BudgetAllocationInput] = Field(default_factory=list, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must contain a non-whitespace character")
        return normalized

    @model_validator(mode="after")
    def require_unique_campaigns(self) -> "BudgetScenarioCreate":
        ids = [item.campaign_id for item in self.allocations]
        if len(ids) != len(set(ids)):
            raise ValueError("a campaign may appear only once in a scenario")
        return self


class BudgetScenarioAllocationsReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocations: list[BudgetAllocationInput] = Field(max_length=500)

    @model_validator(mode="after")
    def require_unique_campaigns(self) -> "BudgetScenarioAllocationsReplace":
        ids = [item.campaign_id for item in self.allocations]
        if len(ids) != len(set(ids)):
            raise ValueError("a campaign may appear only once in a scenario")
        return self


class BudgetScenarioSummary(BaseModel):
    id: UUID
    organization_unit_id: UUID
    name: str
    status: Literal["draft", "archived"]
    allocation_count: int
    created_at: datetime
    updated_at: datetime


class BudgetScenarioAllocationRead(BaseModel):
    campaign_id: UUID
    campaign_name: str
    channel: str
    objective_key: str
    planned_budget_amount: Decimal
    planned_budget_currency: str


class BudgetScenarioDetail(BaseModel):
    id: UUID
    organization_unit_id: UUID
    name: str
    status: Literal["draft", "archived"]
    allocations: list[BudgetScenarioAllocationRead]
    totals_by_currency: dict[str, Decimal]


class BudgetScenarioComparisonItem(BaseModel):
    scenario_id: UUID
    name: str
    allocation_count: int
    totals_by_currency: dict[str, Decimal]


class BudgetScenarioComparison(BaseModel):
    organization_unit_id: UUID
    common_campaign_ids: list[UUID]
    scenarios: list[BudgetScenarioComparisonItem]

class ScenarioObservedMetric(BaseModel):
    actual: int | None
    observed_days: int
    period_days: int
    recorded_day_coverage_percent: Decimal


class BudgetScenarioPerformanceAllocation(BaseModel):
    campaign_id: UUID
    campaign_name: str
    channel: str
    objective_key: str
    planned_budget_amount: Decimal
    planned_budget_currency: str
    recorded_spend_by_currency: dict[str, Decimal]
    actual_spend_in_allocation_currency: Decimal | None
    budget_variance_amount: Decimal | None
    budget_used_percent: Decimal | None
    spend_observed_days: int
    spend_period_days: int
    spend_recorded_day_coverage_percent: Decimal
    metrics: dict[str, ScenarioObservedMetric]


class BudgetScenarioPerformanceContext(BaseModel):
    scenario_id: UUID
    scenario_name: str
    organization_unit_id: UUID
    period_start: date
    period_end: date
    period_calendar_days: int
    metric_definitions: dict[str, MetricDefinition]
    coverage_basis: str
    allocations: list[BudgetScenarioPerformanceAllocation]
    totals_by_currency: dict[str, Decimal]
    currency_conversion_applied: bool
    causal_attribution_applied: bool
    automatic_recommendation_issued: bool

class ScenarioCurrencyReconciliation(BaseModel):
    allocation_count: int
    observed_allocation_count: int
    unobserved_allocation_count: int
    currency_mismatch_allocation_count: int
    planned_amount: Decimal
    comparable_planned_amount: Decimal
    observed_spend_amount: Decimal | None
    variance_amount: Decimal | None
    budget_used_percent: Decimal | None
    allocation_coverage_percent: Decimal


class BudgetScenarioEvidenceSummary(BaseModel):
    scenario_id: UUID
    name: str
    allocation_count: int
    planned_budget_by_currency: dict[str, Decimal]
    reconciliation_by_currency: dict[str, ScenarioCurrencyReconciliation]


class ScenarioMetricObservation(BaseModel):
    actual: int | None
    observed_days: int
    period_days: int
    recorded_day_coverage_percent: Decimal


class BudgetScenarioCampaignAllocation(BaseModel):
    scenario_id: UUID
    scenario_name: str
    planned_budget_amount: Decimal
    planned_budget_currency: str
    actual_spend_in_allocation_currency: Decimal | None
    variance_amount: Decimal | None
    budget_used_percent: Decimal | None


class BudgetScenarioComparisonCampaign(BaseModel):
    campaign_id: UUID
    campaign_name: str
    channel: str
    objective_key: str
    recorded_spend_by_currency: dict[str, Decimal]
    metrics: dict[str, ScenarioMetricObservation]
    scenario_allocations: list[BudgetScenarioCampaignAllocation]


class BudgetScenarioPerformanceComparison(BaseModel):
    organization_unit_id: UUID
    period_start: date
    period_end: date
    period_calendar_days: int
    common_campaign_ids: list[UUID]
    scenarios: list[BudgetScenarioEvidenceSummary]
    campaigns: list[BudgetScenarioComparisonCampaign]
    metric_definitions: dict[str, MetricDefinition]
    interpretation: str
    currency_conversion_applied: bool
    causal_attribution_applied: bool
    counterfactual_outcomes_predicted: bool


async def _require_scenario_permission(
    context: TenantSessionContext,
    *,
    permission_key: str,
    organization_unit_id: UUID,
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Budget scenario action is not authorized for this organization scope")


async def _require_campaign_view(context: TenantSessionContext, organization_unit_id: UUID) -> None:
    if not await has_crm_permission(
        context, permission_key="crm.campaign:view", organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Campaign data is not authorized for this organization scope")


async def _validate_campaigns(
    context: TenantSessionContext,
    *,
    organization_unit_id: UUID,
    campaign_ids: list[UUID],
) -> None:
    await _require_campaign_view(context, organization_unit_id)
    if not campaign_ids:
        return
    campaigns = (
        await context.session.scalars(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == context.access.tenant_id,
                CRMMarketingCampaign.organization_unit_id == organization_unit_id,
                CRMMarketingCampaign.id.in_(campaign_ids),
                CRMMarketingCampaign.status == "draft",
            )
        )
    ).all()
    if len(campaigns) != len(campaign_ids):
        raise HTTPException(status_code=422, detail="Scenario allocations must reference draft campaigns in the same organization")


async def _load_scenario(context: TenantSessionContext, scenario_id: UUID) -> CRMMarketingBudgetScenario:
    scenario = await context.session.scalar(
        select(CRMMarketingBudgetScenario).where(
            CRMMarketingBudgetScenario.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenario.id == scenario_id,
        )
    )
    if scenario is None:
        raise HTTPException(status_code=404, detail="Marketing budget scenario not found")
    return scenario


async def _scenario_totals(
    context: TenantSessionContext,
    *,
    scenario_id: UUID,
) -> dict[str, Decimal]:
    rows = (await context.session.execute(
        select(
            CRMMarketingBudgetScenarioLine.planned_budget_currency,
            func.sum(CRMMarketingBudgetScenarioLine.planned_budget_amount),
        ).where(
            CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenarioLine.scenario_id == scenario_id,
        ).group_by(CRMMarketingBudgetScenarioLine.planned_budget_currency)
    )).all()
    return {currency: amount for currency, amount in rows}


def _audit(
    context: TenantSessionContext,
    *,
    scenario: CRMMarketingBudgetScenario,
    action_key: str,
    allocation_count: int,
) -> None:
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key=action_key,
            target_type="crm_marketing_budget_scenario",
            target_key=str(scenario.id),
            organization_unit_id=scenario.organization_unit_id,
            before_state=None,
            after_state={"status": scenario.status, "allocation_count": allocation_count},
            correlation_id=None,
        )
    )


@router.get("", response_model=list[BudgetScenarioSummary], operation_id="listCRMMarketingBudgetScenarios")
async def list_budget_scenarios(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    status_filter: Literal["draft", "archived"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[BudgetScenarioSummary]:
    filters = [
        CRMMarketingBudgetScenario.tenant_id == context.access.tenant_id,
        CRMMarketingBudgetScenario.organization_unit_id.in_(
            crm_scope_ids(context, permission_key="crm.budget_scenario:view")
        ),
    ]
    if organization_unit_id is not None:
        filters.append(CRMMarketingBudgetScenario.organization_unit_id == organization_unit_id)
    if status_filter is not None:
        filters.append(CRMMarketingBudgetScenario.status == status_filter)
    scenarios = (await context.session.scalars(
        select(CRMMarketingBudgetScenario).where(*filters)
        .order_by(CRMMarketingBudgetScenario.updated_at.desc(), CRMMarketingBudgetScenario.id)
        .limit(limit).offset(offset)
    )).all()
    results = []
    for scenario in scenarios:
        await _require_campaign_view(context, scenario.organization_unit_id)
        count = int(await context.session.scalar(
            select(func.count()).select_from(CRMMarketingBudgetScenarioLine).where(
                CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
                CRMMarketingBudgetScenarioLine.scenario_id == scenario.id,
            )
        ) or 0)
        results.append(BudgetScenarioSummary(
            id=scenario.id,
            organization_unit_id=scenario.organization_unit_id,
            name=scenario.name,
            status=scenario.status,
            allocation_count=count,
            created_at=scenario.created_at,
            updated_at=scenario.updated_at,
        ))
    return results


@router.post(
    "", response_model=BudgetScenarioDetail, status_code=status.HTTP_201_CREATED,
    operation_id="createCRMMarketingBudgetScenario",
)
async def create_budget_scenario(
    payload: BudgetScenarioCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> BudgetScenarioDetail:
    await _require_scenario_permission(
        context, permission_key="crm.budget_scenario:manage",
        organization_unit_id=payload.organization_unit_id,
    )
    await _validate_campaigns(
        context, organization_unit_id=payload.organization_unit_id,
        campaign_ids=[item.campaign_id for item in payload.allocations],
    )
    scenario = CRMMarketingBudgetScenario(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id, name=payload.name, status="draft",
    )
    context.session.add(scenario)
    await context.session.flush()
    lines = [
        CRMMarketingBudgetScenarioLine(
            tenant_id=context.access.tenant_id,
            organization_unit_id=payload.organization_unit_id,
            scenario_id=scenario.id,
            campaign_id=item.campaign_id,
            planned_budget_amount=item.planned_budget_amount,
            planned_budget_currency=item.planned_budget_currency,
        )
        for item in payload.allocations
    ]
    context.session.add_all(lines)
    await context.session.flush()
    _audit(context, scenario=scenario, action_key="crm_marketing_budget_scenario.created", allocation_count=len(lines))
    await context.session.flush()
    return await _scenario_detail(context, scenario)


async def _scenario_detail(
    context: TenantSessionContext,
    scenario: CRMMarketingBudgetScenario,
) -> BudgetScenarioDetail:
    rows = (await context.session.execute(
        select(
            CRMMarketingBudgetScenarioLine.campaign_id,
            CRMMarketingBudgetScenarioLine.planned_budget_amount,
            CRMMarketingBudgetScenarioLine.planned_budget_currency,
            CRMMarketingCampaign.name,
            CRMMarketingCampaign.channel,
            CRMMarketingCampaign.objective_key,
        ).join(
            CRMMarketingCampaign,
            (CRMMarketingCampaign.tenant_id == CRMMarketingBudgetScenarioLine.tenant_id)
            & (CRMMarketingCampaign.id == CRMMarketingBudgetScenarioLine.campaign_id)
            & (CRMMarketingCampaign.organization_unit_id == CRMMarketingBudgetScenarioLine.organization_unit_id),
        ).where(
            CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenarioLine.scenario_id == scenario.id,
        ).order_by(CRMMarketingCampaign.name, CRMMarketingCampaign.id)
    )).all()
    return BudgetScenarioDetail(
        id=scenario.id,
        organization_unit_id=scenario.organization_unit_id,
        name=scenario.name,
        status=scenario.status,
        allocations=[
            BudgetScenarioAllocationRead(
                campaign_id=campaign_id,
                campaign_name=name,
                channel=channel,
                objective_key=objective_key,
                planned_budget_amount=amount,
                planned_budget_currency=currency,
            )
            for campaign_id, amount, currency, name, channel, objective_key in rows
        ],
        totals_by_currency=await _scenario_totals(context, scenario_id=scenario.id),
    )


@router.get("/compare", response_model=BudgetScenarioComparison, operation_id="compareCRMMarketingBudgetScenarios")
async def compare_budget_scenarios(
    scenario_ids: list[UUID] = Query(min_length=2, max_length=5),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> BudgetScenarioComparison:
    if len(scenario_ids) != len(set(scenario_ids)):
        raise HTTPException(status_code=422, detail="Scenario IDs must be unique")
    scenarios = (await context.session.scalars(
        select(CRMMarketingBudgetScenario).where(
            CRMMarketingBudgetScenario.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenario.id.in_(scenario_ids),
        )
    )).all()
    if len(scenarios) != len(scenario_ids):
        raise HTTPException(status_code=404, detail="One or more marketing budget scenarios were not found")
    organization_ids = {scenario.organization_unit_id for scenario in scenarios}
    if len(organization_ids) != 1:
        raise HTTPException(status_code=422, detail="Scenarios must belong to the same organization scope")
    organization_unit_id = next(iter(organization_ids))
    await _require_scenario_permission(
        context, permission_key="crm.budget_scenario:view",
        organization_unit_id=organization_unit_id,
    )
    await _require_campaign_view(context, organization_unit_id)
    rows = (await context.session.execute(
        select(
            CRMMarketingBudgetScenarioLine.scenario_id,
            CRMMarketingBudgetScenarioLine.campaign_id,
            CRMMarketingBudgetScenarioLine.planned_budget_amount,
            CRMMarketingBudgetScenarioLine.planned_budget_currency,
        ).where(
            CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenarioLine.scenario_id.in_(scenario_ids),
        )
    )).all()
    campaigns_by_scenario: dict[UUID, set[UUID]] = {item.id: set() for item in scenarios}
    totals: dict[UUID, dict[str, Decimal]] = {item.id: {} for item in scenarios}
    for scenario_id, campaign_id, amount, currency in rows:
        campaigns_by_scenario[scenario_id].add(campaign_id)
        totals[scenario_id][currency] = totals[scenario_id].get(currency, Decimal("0")) + amount
    reference = next(iter(campaigns_by_scenario.values()))
    if any(campaign_ids != reference for campaign_ids in campaigns_by_scenario.values()):
        raise HTTPException(status_code=422, detail="Scenarios can be compared only when they allocate the same campaign set")
    return BudgetScenarioComparison(
        organization_unit_id=organization_unit_id,
        common_campaign_ids=sorted(reference, key=str),
        scenarios=[
            BudgetScenarioComparisonItem(
                scenario_id=scenario.id, name=scenario.name,
                allocation_count=len(campaigns_by_scenario[scenario.id]),
                totals_by_currency=totals[scenario.id],
            )
            for scenario in sorted(scenarios, key=lambda item: item.name)
        ],
    )




@router.get(
    "/compare/performance-context",
    response_model=BudgetScenarioPerformanceComparison,
    operation_id="compareCRMMarketingBudgetScenarioPerformanceContext",
)
async def compare_budget_scenario_performance_context(
    scenario_ids: list[UUID] = Query(min_length=2, max_length=5),
    period_start: date = Query(...),
    period_end: date = Query(...),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> BudgetScenarioPerformanceComparison:
    if period_start > period_end or (period_end - period_start).days >= 366:
        raise HTTPException(status_code=422, detail="Period must be ordered and no longer than 366 days")
    if len(scenario_ids) != len(set(scenario_ids)):
        raise HTTPException(status_code=422, detail="Scenario IDs must be unique")

    scenarios = (await context.session.scalars(
        select(CRMMarketingBudgetScenario).where(
            CRMMarketingBudgetScenario.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenario.id.in_(scenario_ids),
        )
    )).all()
    if len(scenarios) != len(scenario_ids):
        raise HTTPException(status_code=404, detail="One or more marketing budget scenarios were not found")
    organization_ids = {item.organization_unit_id for item in scenarios}
    if len(organization_ids) != 1:
        raise HTTPException(status_code=422, detail="Scenarios must belong to the same organization scope")
    organization_unit_id = next(iter(organization_ids))
    await _require_scenario_permission(
        context, permission_key="crm.budget_scenario:view",
        organization_unit_id=organization_unit_id,
    )
    await _require_campaign_view(context, organization_unit_id)

    lines = (await context.session.execute(
        select(
            CRMMarketingBudgetScenarioLine.scenario_id,
            CRMMarketingBudgetScenarioLine.campaign_id,
            CRMMarketingBudgetScenarioLine.planned_budget_amount,
            CRMMarketingBudgetScenarioLine.planned_budget_currency,
            CRMMarketingCampaign.name,
            CRMMarketingCampaign.channel,
            CRMMarketingCampaign.objective_key,
        ).join(
            CRMMarketingCampaign,
            (CRMMarketingCampaign.tenant_id == CRMMarketingBudgetScenarioLine.tenant_id)
            & (CRMMarketingCampaign.organization_unit_id == CRMMarketingBudgetScenarioLine.organization_unit_id)
            & (CRMMarketingCampaign.id == CRMMarketingBudgetScenarioLine.campaign_id),
        ).where(
            CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenarioLine.organization_unit_id == organization_unit_id,
            CRMMarketingBudgetScenarioLine.scenario_id.in_(scenario_ids),
        )
    )).all()
    scenario_campaign_ids: dict[UUID, set[UUID]] = {item.id: set() for item in scenarios}
    line_by_scenario_campaign: dict[UUID, dict[UUID, object]] = {
        item.id: {} for item in scenarios
    }
    campaign_metadata = {}
    for line in lines:
        scenario_campaign_ids[line.scenario_id].add(line.campaign_id)
        line_by_scenario_campaign[line.scenario_id][line.campaign_id] = line
        campaign_metadata[line.campaign_id] = (
            line.name, line.channel, line.objective_key
        )
    reference_campaign_ids = next(iter(scenario_campaign_ids.values()))
    if any(ids != reference_campaign_ids for ids in scenario_campaign_ids.values()):
        raise HTTPException(
            status_code=422,
            detail="Scenarios can be compared only when they allocate the same campaign set",
        )
    common_campaign_ids = sorted(reference_campaign_ids, key=str)
    period_days = (period_end - period_start).days + 1
    measurements = []
    if common_campaign_ids:
        measurements = (await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id == organization_unit_id,
                CRMMarketingCampaignMeasurement.campaign_id.in_(common_campaign_ids),
                CRMMarketingCampaignMeasurement.measured_on >= period_start,
                CRMMarketingCampaignMeasurement.measured_on <= period_end,
            ).order_by(CRMMarketingCampaignMeasurement.measured_on)
        )).all()

    rows_by_campaign: dict[UUID, list[CRMMarketingCampaignMeasurement]] = {
        campaign_id: [] for campaign_id in common_campaign_ids
    }
    for measurement in measurements:
        rows_by_campaign[measurement.campaign_id].append(measurement)

    def observed_metric(values: list[int | None]) -> ScenarioMetricObservation:
        present = [value for value in values if value is not None]
        days = len(present)
        return ScenarioMetricObservation(
            actual=sum(present) if present else None,
            observed_days=days,
            period_days=period_days,
            recorded_day_coverage_percent=(
                (Decimal(days) * Decimal("100") / Decimal(period_days)).quantize(Decimal("0.01"))
                if period_days > 0 else Decimal("0")
            ),
        )

    spend_by_campaign: dict[UUID, dict[str, Decimal]] = {}
    for campaign_id, campaign_measurements in rows_by_campaign.items():
        currency_totals: dict[str, Decimal] = {}
        for measurement in campaign_measurements:
            if measurement.actual_spend_amount is not None and measurement.actual_spend_currency is not None:
                currency = measurement.actual_spend_currency
                currency_totals[currency] = currency_totals.get(currency, Decimal("0")) + measurement.actual_spend_amount
        spend_by_campaign[campaign_id] = currency_totals

    scenario_summaries: list[BudgetScenarioEvidenceSummary] = []
    for scenario in sorted(scenarios, key=lambda item: (item.name.casefold(), str(item.id))):
        scenario_lines = line_by_scenario_campaign[scenario.id]
        planned_by_currency: dict[str, Decimal] = {}
        reconciliation_state: dict[str, dict[str, object]] = {}
        for campaign_id, line in scenario_lines.items():
            currency = line.planned_budget_currency
            planned_by_currency[currency] = planned_by_currency.get(currency, Decimal("0")) + line.planned_budget_amount
            bucket = reconciliation_state.setdefault(currency, {
                "allocation_count": 0,
                "observed_allocation_count": 0,
                "unobserved_allocation_count": 0,
                "currency_mismatch_allocation_count": 0,
                "planned_amount": Decimal("0"),
                "comparable_planned_amount": Decimal("0"),
                "observed_spend_amount": Decimal("0"),
            })
            bucket["allocation_count"] += 1
            bucket["planned_amount"] += line.planned_budget_amount
            recorded = spend_by_campaign.get(campaign_id, {})
            if currency in recorded:
                bucket["observed_allocation_count"] += 1
                bucket["comparable_planned_amount"] += line.planned_budget_amount
                bucket["observed_spend_amount"] += recorded[currency]
            else:
                bucket["unobserved_allocation_count"] += 1
                if recorded:
                    bucket["currency_mismatch_allocation_count"] += 1

        reconciliation = {}
        for currency, state in reconciliation_state.items():
            observed_count = int(state["observed_allocation_count"])
            allocation_count = int(state["allocation_count"])
            actual = state["observed_spend_amount"] if observed_count else None
            comparable_plan = state["comparable_planned_amount"]
            reconciliation[currency] = ScenarioCurrencyReconciliation(
                allocation_count=allocation_count,
                observed_allocation_count=observed_count,
                unobserved_allocation_count=int(state["unobserved_allocation_count"]),
                currency_mismatch_allocation_count=int(state["currency_mismatch_allocation_count"]),
                planned_amount=state["planned_amount"],
                comparable_planned_amount=comparable_plan,
                observed_spend_amount=actual,
                variance_amount=(comparable_plan - actual) if actual is not None else None,
                budget_used_percent=(
                    (actual * Decimal("100") / comparable_plan).quantize(Decimal("0.01"))
                    if actual is not None and comparable_plan > 0 else None
                ),
                allocation_coverage_percent=(
                    (Decimal(observed_count) * Decimal("100") / Decimal(allocation_count)).quantize(Decimal("0.01"))
                    if allocation_count else Decimal("0")
                ),
            )
        scenario_summaries.append(BudgetScenarioEvidenceSummary(
            scenario_id=scenario.id,
            name=scenario.name,
            allocation_count=len(scenario_lines),
            planned_budget_by_currency=planned_by_currency,
            reconciliation_by_currency=reconciliation,
        ))

    campaign_items = []
    for campaign_id in common_campaign_ids:
        name, channel, objective = campaign_metadata[campaign_id]
        campaign_measurements = rows_by_campaign[campaign_id]
        scenario_allocations = []
        for scenario in sorted(scenarios, key=lambda item: (item.name.casefold(), str(item.id))):
            line = line_by_scenario_campaign[scenario.id][campaign_id]
            currency = line.planned_budget_currency
            actual = spend_by_campaign.get(campaign_id, {}).get(currency)
            scenario_allocations.append(BudgetScenarioCampaignAllocation(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                planned_budget_amount=line.planned_budget_amount,
                planned_budget_currency=currency,
                actual_spend_in_allocation_currency=actual,
                variance_amount=(line.planned_budget_amount - actual) if actual is not None else None,
                budget_used_percent=(
                    (actual * Decimal("100") / line.planned_budget_amount).quantize(Decimal("0.01"))
                    if actual is not None and line.planned_budget_amount > 0 else None
                ),
            ))
        campaign_items.append(BudgetScenarioComparisonCampaign(
            campaign_id=campaign_id,
            campaign_name=name,
            channel=channel,
            objective_key=objective,
            recorded_spend_by_currency=spend_by_campaign.get(campaign_id, {}),
            metrics={
                "leads": observed_metric([item.leads for item in campaign_measurements]),
                "conversions": observed_metric([item.conversions for item in campaign_measurements]),
            },
            scenario_allocations=scenario_allocations,
        ))

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_budget_scenario.performance_comparison_viewed",
        target_type="crm_marketing_budget_scenario_performance_comparison",
        target_key=",".join(str(item.id) for item in sorted(scenarios, key=lambda item: str(item.id))),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "scenario_count": len(scenarios),
            "campaign_count": len(common_campaign_ids),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    metric_definitions = {
        key: definition
        for key in ("actual_spend", "leads", "conversions")
        if (definition := get_metric_definition(key)) is not None
    }
    return BudgetScenarioPerformanceComparison(
        organization_unit_id=organization_unit_id,
        period_start=period_start,
        period_end=period_end,
        period_calendar_days=period_days,
        common_campaign_ids=common_campaign_ids,
        scenarios=scenario_summaries,
        campaigns=campaign_items,
        metric_definitions=metric_definitions,
        interpretation=(
            "Observed results are attached to the common campaigns and are not predictions of scenario outcomes. "
            "Variances include only allocations with recorded spend in the same currency."
        ),
        currency_conversion_applied=False,
        causal_attribution_applied=False,
        counterfactual_outcomes_predicted=False,
    )


@router.get(
    "/{scenario_id}/performance-context",
    response_model=BudgetScenarioPerformanceContext,
    operation_id="getCRMMarketingBudgetScenarioPerformanceContext",
)
async def get_budget_scenario_performance_context(
    scenario_id: UUID,
    period_start: date,
    period_end: date,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> BudgetScenarioPerformanceContext:
    if period_start > period_end or (period_end - period_start).days >= 366:
        raise HTTPException(status_code=422, detail="Period must be ordered and no longer than 366 days")
    scenario = await _load_scenario(context, scenario_id)
    await _require_scenario_permission(
        context, permission_key="crm.budget_scenario:view",
        organization_unit_id=scenario.organization_unit_id,
    )
    await _require_campaign_view(context, scenario.organization_unit_id)

    campaign_rows = (await context.session.execute(
        select(
            CRMMarketingBudgetScenarioLine.campaign_id,
            CRMMarketingBudgetScenarioLine.planned_budget_amount,
            CRMMarketingBudgetScenarioLine.planned_budget_currency,
            CRMMarketingCampaign.name,
            CRMMarketingCampaign.channel,
            CRMMarketingCampaign.objective_key,
        ).join(
            CRMMarketingCampaign,
            (CRMMarketingCampaign.tenant_id == CRMMarketingBudgetScenarioLine.tenant_id)
            & (CRMMarketingCampaign.organization_unit_id == CRMMarketingBudgetScenarioLine.organization_unit_id)
            & (CRMMarketingCampaign.id == CRMMarketingBudgetScenarioLine.campaign_id),
        ).where(
            CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenarioLine.organization_unit_id == scenario.organization_unit_id,
            CRMMarketingBudgetScenarioLine.scenario_id == scenario.id,
        ).order_by(CRMMarketingCampaign.name, CRMMarketingCampaign.id)
    )).all()
    campaign_ids = [row.campaign_id for row in campaign_rows]
    measurements = []
    if campaign_ids:
        measurements = (await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id == scenario.organization_unit_id,
                CRMMarketingCampaignMeasurement.campaign_id.in_(campaign_ids),
                CRMMarketingCampaignMeasurement.measured_on >= period_start,
                CRMMarketingCampaignMeasurement.measured_on <= period_end,
            ).order_by(CRMMarketingCampaignMeasurement.measured_on)
        )).all()

    rows_by_campaign: dict[UUID, list[CRMMarketingCampaignMeasurement]] = {}
    for measurement in measurements:
        rows_by_campaign.setdefault(measurement.campaign_id, []).append(measurement)

    period_days = (period_end - period_start).days + 1

    def observed_metric(values: list[int | None]) -> ScenarioObservedMetric:
        present = [value for value in values if value is not None]
        observed_days = len(present)
        return ScenarioObservedMetric(
            actual=sum(present) if present else None,
            observed_days=observed_days,
            period_days=period_days,
            recorded_day_coverage_percent=(
                (Decimal(observed_days) * Decimal("100") / Decimal(period_days)).quantize(Decimal("0.01"))
                if period_days > 0 else Decimal("0")
            ),
        )

    allocations: list[BudgetScenarioPerformanceAllocation] = []
    for row in campaign_rows:
        campaign_measurements = rows_by_campaign.get(row.campaign_id, [])
        spend_by_currency: dict[str, Decimal] = {}
        spend_days_by_currency: dict[str, int] = {}
        for measurement in campaign_measurements:
            if measurement.actual_spend_amount is None or measurement.actual_spend_currency is None:
                continue
            currency = measurement.actual_spend_currency
            spend_by_currency[currency] = spend_by_currency.get(currency, Decimal("0")) + measurement.actual_spend_amount
            spend_days_by_currency[currency] = spend_days_by_currency.get(currency, 0) + 1

        allocation_currency = row.planned_budget_currency
        matching_spend = spend_by_currency.get(allocation_currency)
        spend_days = spend_days_by_currency.get(allocation_currency, 0)
        variance = row.planned_budget_amount - matching_spend if matching_spend is not None else None
        used_percent = (
            (matching_spend * Decimal("100") / row.planned_budget_amount).quantize(Decimal("0.01"))
            if matching_spend is not None and row.planned_budget_amount > 0
            else None
        )
        allocations.append(BudgetScenarioPerformanceAllocation(
            campaign_id=row.campaign_id,
            campaign_name=row.name,
            channel=row.channel,
            objective_key=row.objective_key,
            planned_budget_amount=row.planned_budget_amount,
            planned_budget_currency=allocation_currency,
            recorded_spend_by_currency=spend_by_currency,
            actual_spend_in_allocation_currency=matching_spend,
            budget_variance_amount=variance,
            budget_used_percent=used_percent,
            spend_observed_days=spend_days,
            spend_period_days=period_days,
            spend_recorded_day_coverage_percent=(
                (Decimal(spend_days) * Decimal("100") / Decimal(period_days)).quantize(Decimal("0.01"))
                if period_days > 0 else Decimal("0")
            ),
            metrics={
                "leads": observed_metric([item.leads for item in campaign_measurements]),
                "conversions": observed_metric([item.conversions for item in campaign_measurements]),
            },
        ))

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_budget_scenario.performance_context_viewed",
        target_type="crm_marketing_budget_scenario_performance_context",
        target_key=str(scenario.id),
        organization_unit_id=scenario.organization_unit_id,
        before_state=None,
        after_state={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "allocation_count": len(allocations),
            "measurement_count": len(measurements),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    metric_definitions = {
        key: definition
        for key in ("actual_spend", "leads", "conversions")
        if (definition := get_metric_definition(key)) is not None
    }
    return BudgetScenarioPerformanceContext(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        organization_unit_id=scenario.organization_unit_id,
        period_start=period_start,
        period_end=period_end,
        period_calendar_days=period_days,
        metric_definitions=metric_definitions,
        coverage_basis=(
            "Coverage is observed measurement days divided by calendar days in the selected period. "
            "Missing days are not zero; spend variance uses only recorded spend in the allocation currency."
        ),
        allocations=allocations,
        totals_by_currency=await _scenario_totals(context, scenario_id=scenario.id),
        currency_conversion_applied=False,
        causal_attribution_applied=False,
        automatic_recommendation_issued=False,
    )


@router.get("/{scenario_id}", response_model=BudgetScenarioDetail, operation_id="getCRMMarketingBudgetScenario")
async def get_budget_scenario(
    scenario_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> BudgetScenarioDetail:
    scenario = await _load_scenario(context, scenario_id)
    await _require_scenario_permission(
        context, permission_key="crm.budget_scenario:view",
        organization_unit_id=scenario.organization_unit_id,
    )
    await _require_campaign_view(context, scenario.organization_unit_id)
    return await _scenario_detail(context, scenario)


@router.put("/{scenario_id}/allocations", response_model=BudgetScenarioDetail, operation_id="replaceCRMMarketingBudgetScenarioAllocations")
async def replace_budget_scenario_allocations(
    scenario_id: UUID,
    payload: BudgetScenarioAllocationsReplace,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> BudgetScenarioDetail:
    scenario = await context.session.scalar(
        select(CRMMarketingBudgetScenario).where(
            CRMMarketingBudgetScenario.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenario.id == scenario_id,
        ).with_for_update()
    )
    if scenario is None:
        raise HTTPException(status_code=404, detail="Marketing budget scenario not found")
    await _require_scenario_permission(
        context, permission_key="crm.budget_scenario:manage",
        organization_unit_id=scenario.organization_unit_id,
    )
    if scenario.status != "draft":
        raise HTTPException(status_code=409, detail="Archived scenarios cannot be changed")
    await _validate_campaigns(
        context, organization_unit_id=scenario.organization_unit_id,
        campaign_ids=[item.campaign_id for item in payload.allocations],
    )
    await context.session.execute(
        delete(CRMMarketingBudgetScenarioLine).where(
            CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenarioLine.scenario_id == scenario.id,
        )
    )
    lines = [
        CRMMarketingBudgetScenarioLine(
            tenant_id=context.access.tenant_id,
            organization_unit_id=scenario.organization_unit_id,
            scenario_id=scenario.id,
            campaign_id=item.campaign_id,
            planned_budget_amount=item.planned_budget_amount,
            planned_budget_currency=item.planned_budget_currency,
        )
        for item in payload.allocations
    ]
    context.session.add_all(lines)
    await context.session.flush()
    scenario.updated_at = datetime.now(timezone.utc)
    _audit(context, scenario=scenario, action_key="crm_marketing_budget_scenario.allocations_replaced", allocation_count=len(lines))
    await context.session.flush()
    return await _scenario_detail(context, scenario)


@router.post("/{scenario_id}/archive", status_code=status.HTTP_204_NO_CONTENT, operation_id="archiveCRMMarketingBudgetScenario")
async def archive_budget_scenario(
    scenario_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    scenario = await context.session.scalar(
        select(CRMMarketingBudgetScenario).where(
            CRMMarketingBudgetScenario.tenant_id == context.access.tenant_id,
            CRMMarketingBudgetScenario.id == scenario_id,
        ).with_for_update()
    )
    if scenario is None:
        raise HTTPException(status_code=404, detail="Marketing budget scenario not found")
    await _require_scenario_permission(
        context, permission_key="crm.budget_scenario:manage",
        organization_unit_id=scenario.organization_unit_id,
    )
    if scenario.status == "draft":
        scenario.status = "archived"
        scenario.updated_at = datetime.now(timezone.utc)
        await context.session.flush()
        count = int(await context.session.scalar(
            select(func.count()).select_from(CRMMarketingBudgetScenarioLine).where(
                CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
                CRMMarketingBudgetScenarioLine.scenario_id == scenario.id,
            )
        ) or 0)
        _audit(context, scenario=scenario, action_key="crm_marketing_budget_scenario.archived", allocation_count=count)
        await context.session.flush()
