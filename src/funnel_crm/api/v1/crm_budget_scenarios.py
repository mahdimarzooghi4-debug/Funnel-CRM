"""Tenant- and organization-scoped planning scenarios for campaign budgets."""

from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingBudgetScenario,
    CRMMarketingBudgetScenarioLine,
    CRMMarketingCampaign,
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
    created_at: object
    updated_at: object


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
    _audit(context, scenario, "crm_marketing_budget_scenario.created", len(lines))
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
            & (CRMMarketingCampaign.id == CRMMarketingBudgetScenarioLine.campaign_id),
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
    scenario.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    _audit(context, scenario, "crm_marketing_budget_scenario.allocations_replaced", len(lines))
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
        scenario.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        await context.session.flush()
        count = int(await context.session.scalar(
            select(func.count()).select_from(CRMMarketingBudgetScenarioLine).where(
                CRMMarketingBudgetScenarioLine.tenant_id == context.access.tenant_id,
                CRMMarketingBudgetScenarioLine.scenario_id == scenario.id,
            )
        ) or 0)
        _audit(context, scenario, "crm_marketing_budget_scenario.archived", count)
        await context.session.flush()
