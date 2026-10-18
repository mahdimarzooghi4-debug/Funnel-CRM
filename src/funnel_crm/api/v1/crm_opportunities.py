"""Sales pipeline and opportunity operations for scoped CRM teams."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMOpportunity,
    CRMPipeline,
    CRMProfile,
    OrganizationUnit,
    Workspace,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/opportunities", tags=["CRM sales"])


class OpportunityStageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    name: str = Field(min_length=1, max_length=120)
    position: int = Field(ge=1, le=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("stage name must not be blank")
        return value


class OpportunityPipelineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    display_name: str = Field(min_length=1, max_length=160)
    stages: list[OpportunityStageInput] = Field(min_length=2, max_length=30)
    is_default: bool = False

    @model_validator(mode="after")
    def unique_stage_keys_and_positions(self):
        keys = [stage.key for stage in self.stages]
        positions = [stage.position for stage in self.stages]
        if len(keys) != len(set(keys)) or len(positions) != len(set(positions)):
            raise ValueError("stage keys and positions must be unique")
        return self


class OpportunityPipelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pipeline_key: str
    display_name: str
    stages: list[dict[str, Any]]
    is_default: bool


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    profile_id: UUID | None = None
    pipeline_id: UUID
    name: str = Field(min_length=1, max_length=200)
    stage_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    expected_close_date: date | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("opportunity name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_amount_pair(self):
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be provided together")
        return self


class OpportunityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    stage_key: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    expected_close_date: date | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("opportunity name must not be blank")
        return value


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    profile_id: UUID | None
    pipeline_id: UUID
    name: str
    stage_key: str
    amount: Decimal | None
    currency: str | None
    expected_close_date: date | None
    created_at: datetime
    updated_at: datetime


class OpportunityPage(BaseModel):
    items: list[OpportunityRead]
    total: int
    limit: int
    offset: int


async def _require(context: TenantSessionContext, permission_key: str, unit_id: UUID) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=unit_id
    ):
        raise HTTPException(status_code=403, detail="CRM opportunity action is not authorized")


def _audit(
    context: TenantSessionContext,
    *,
    action_key: str,
    opportunity: CRMOpportunity,
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> None:
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key=action_key,
        target_type="crm_opportunity",
        target_key=str(opportunity.id),
        organization_unit_id=opportunity.organization_unit_id,
        before_state=before,
        after_state=after,
        correlation_id=None,
    ))


def _state(opportunity: CRMOpportunity) -> dict[str, Any]:
    return {
        "organization_unit_id": str(opportunity.organization_unit_id),
        "profile_id": str(opportunity.profile_id) if opportunity.profile_id else None,
        "pipeline_id": str(opportunity.pipeline_id),
        "name": opportunity.name,
        "stage_key": opportunity.stage_key,
        "amount": str(opportunity.amount) if opportunity.amount is not None else None,
        "currency": opportunity.currency,
        "expected_close_date": opportunity.expected_close_date.isoformat()
        if opportunity.expected_close_date else None,
    }


async def _validate_pipeline_stage(
    context: TenantSessionContext, pipeline_id: UUID, stage_key: str
) -> CRMPipeline:
    pipeline = await context.session.scalar(select(CRMPipeline).where(
        CRMPipeline.tenant_id == context.access.tenant_id,
        CRMPipeline.id == pipeline_id,
        CRMPipeline.entity_kind == "opportunity",
    ))
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Opportunity pipeline not found")
    if not any(
        isinstance(stage, dict) and stage.get("key") == stage_key
        for stage in pipeline.stages
    ):
        raise HTTPException(status_code=422, detail="Stage is not part of the selected opportunity pipeline")
    return pipeline


@router.get("/pipelines", response_model=list[OpportunityPipelineRead], operation_id="listCRMOpportunityPipelines")
async def list_opportunity_pipelines(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[OpportunityPipelineRead]:
    scopes = crm_scope_ids(context, permission_key="crm.opportunity:view")
    has_scope = await context.session.scalar(select(OrganizationUnit.id).where(
        OrganizationUnit.tenant_id == context.access.tenant_id,
        OrganizationUnit.id.in_(scopes),
    ).limit(1))
    if has_scope is None:
        raise HTTPException(status_code=403, detail="CRM opportunity view is not authorized")
    pipelines = (await context.session.scalars(select(CRMPipeline).where(
        CRMPipeline.tenant_id == context.access.tenant_id,
        CRMPipeline.entity_kind == "opportunity",
    ).order_by(CRMPipeline.is_default.desc(), CRMPipeline.display_name, CRMPipeline.id))).all()
    return [OpportunityPipelineRead.model_validate(pipeline) for pipeline in pipelines]


@router.post(
    "/pipelines",
    response_model=OpportunityPipelineRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCRMOpportunityPipeline",
)
async def create_opportunity_pipeline(
    payload: OpportunityPipelineCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> OpportunityPipelineRead:
    workspace = await context.session.get(Workspace, context.access.tenant_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="CRM workspace not found")
    await _require(context, "crm.pipeline:manage", workspace.root_organization_id)
    if payload.is_default:
        existing_default = await context.session.scalar(select(CRMPipeline.id).where(
            CRMPipeline.tenant_id == context.access.tenant_id,
            CRMPipeline.entity_kind == "opportunity",
            CRMPipeline.is_default.is_(True),
        ))
        if existing_default is not None:
            raise HTTPException(status_code=409, detail="A default opportunity pipeline already exists")
    pipeline = CRMPipeline(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        pipeline_key=payload.pipeline_key,
        entity_kind="opportunity",
        display_name=payload.display_name.strip(),
        stages=[stage.model_dump() for stage in sorted(payload.stages, key=lambda item: item.position)],
        is_default=payload.is_default,
    )
    context.session.add(pipeline)
    await context.session.flush()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_opportunity_pipeline.created",
        target_type="crm_pipeline",
        target_key=str(pipeline.id),
        organization_unit_id=workspace.root_organization_id,
        before_state=None,
        after_state={"pipeline_key": pipeline.pipeline_key, "stage_count": len(pipeline.stages),
                     "is_default": pipeline.is_default},
        correlation_id=None,
    ))
    await context.session.flush()
    return OpportunityPipelineRead.model_validate(pipeline)


@router.get("", response_model=OpportunityPage, operation_id="listCRMOpportunities")
async def list_opportunities(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    pipeline_id: UUID | None = None,
    stage_key: str | None = Query(default=None, min_length=1, max_length=80),
    profile_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> OpportunityPage:
    scopes = crm_scope_ids(context, permission_key="crm.opportunity:view")
    filters = [
        CRMOpportunity.tenant_id == context.access.tenant_id,
        CRMOpportunity.organization_unit_id.in_(scopes),
    ]
    if organization_unit_id is not None:
        if not await has_crm_permission(context, permission_key="crm.opportunity:view",
                                        organization_unit_id=organization_unit_id):
            raise HTTPException(status_code=404, detail="CRM opportunity scope not found")
        filters.append(CRMOpportunity.organization_unit_id == organization_unit_id)
    if pipeline_id is not None:
        filters.append(CRMOpportunity.pipeline_id == pipeline_id)
    if stage_key is not None:
        filters.append(CRMOpportunity.stage_key == stage_key)
    if profile_id is not None:
        filters.append(CRMOpportunity.profile_id == profile_id)

    total = int(await context.session.scalar(
        select(func.count()).select_from(CRMOpportunity).where(*filters)
    ) or 0)
    rows = (await context.session.scalars(select(CRMOpportunity).where(*filters)
        .order_by(CRMOpportunity.updated_at.desc(), CRMOpportunity.id)
        .limit(limit).offset(offset))).all()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_opportunity.list_viewed",
        target_type="crm_opportunity_list",
        target_key=str(organization_unit_id or "authorized-scope"),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={"total": total, "returned": len(rows), "limit": limit, "offset": offset,
                     "pipeline_id": str(pipeline_id) if pipeline_id else None,
                     "stage_key": stage_key},
        correlation_id=None,
    ))
    await context.session.flush()
    return OpportunityPage(items=[OpportunityRead.model_validate(row) for row in rows],
                           total=total, limit=limit, offset=offset)


@router.post("", response_model=OpportunityRead, status_code=status.HTTP_201_CREATED,
             operation_id="createCRMOpportunity")
async def create_opportunity(
    payload: OpportunityCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> OpportunityRead:
    await _require(context, "crm.opportunity:create", payload.organization_unit_id)
    pipeline = await _validate_pipeline_stage(context, payload.pipeline_id, payload.stage_key)
    if payload.profile_id is not None:
        profile = await context.session.scalar(select(CRMProfile).where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.id == payload.profile_id,
            CRMProfile.organization_unit_id == payload.organization_unit_id,
            CRMProfile.archived_at.is_(None),
            CRMProfile.merged_into_profile_id.is_(None),
        ))
        if profile is None:
            raise HTTPException(status_code=404, detail="CRM profile not found")
    opportunity = CRMOpportunity(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        profile_id=payload.profile_id,
        pipeline_id=pipeline.id,
        name=payload.name,
        stage_key=payload.stage_key,
        amount=payload.amount,
        currency=payload.currency,
        expected_close_date=payload.expected_close_date,
    )
    context.session.add(opportunity)
    await context.session.flush()
    _audit(context, action_key="crm_opportunity.created", opportunity=opportunity,
           before=None, after=_state(opportunity))
    await context.session.flush()
    return OpportunityRead.model_validate(opportunity)


@router.patch("/{opportunity_id}", response_model=OpportunityRead,
              operation_id="updateCRMOpportunity")
async def update_opportunity(
    opportunity_id: UUID,
    payload: OpportunityUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> OpportunityRead:
    opportunity = await context.session.scalar(select(CRMOpportunity).where(
        CRMOpportunity.tenant_id == context.access.tenant_id,
        CRMOpportunity.id == opportunity_id,
    ).with_for_update())
    if opportunity is None:
        raise HTTPException(status_code=404, detail="CRM opportunity not found")
    await _require(context, "crm.opportunity:update", opportunity.organization_unit_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="Opportunity name cannot be cleared")
    new_stage = changes.get("stage_key", opportunity.stage_key)
    if new_stage is None:
        raise HTTPException(status_code=422, detail="Opportunity stage cannot be cleared")
    await _validate_pipeline_stage(context, opportunity.pipeline_id, new_stage)
    new_amount = changes.get("amount", opportunity.amount)
    new_currency = changes.get("currency", opportunity.currency)
    if (new_amount is None) != (new_currency is None):
        raise HTTPException(status_code=422, detail="amount and currency must be provided together")
    before = _state(opportunity)
    for key, value in changes.items():
        setattr(opportunity, key, value)
    opportunity.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit(context, action_key="crm_opportunity.updated", opportunity=opportunity,
           before=before, after=_state(opportunity))
    await context.session.flush()
    return OpportunityRead.model_validate(opportunity)
