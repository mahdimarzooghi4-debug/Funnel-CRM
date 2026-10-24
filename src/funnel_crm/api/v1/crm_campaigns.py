"""Marketing campaign planning endpoints; sending and activation are intentionally absent."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import AuditEvent, CRMMarketingCampaign, CRMProfileSegment
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/campaigns", tags=["CRM marketing campaigns"])
CampaignChannel = Literal["email", "phone", "messaging", "social", "web", "store", "field", "other"]


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    segment_id: UUID
    name: str = Field(min_length=1, max_length=160)
    objective_key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: CampaignChannel
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must contain a non-whitespace character")
        return normalized

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("schedule timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_schedule(self) -> "CampaignCreate":
        if self.starts_at is not None and self.ends_at is not None and self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be earlier than ends_at")
        return self


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    objective_key: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: CampaignChannel | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("segment_id", "name", "objective_key", "channel")
    @classmethod
    def reject_null_for_nonnullable(cls, value):
        if value is None:
            raise ValueError("explicit null is not allowed for this field")
        if isinstance(value, str) and not value.strip():
            raise ValueError("value must contain a non-whitespace character")
        return value.strip() if isinstance(value, str) and value == value.strip() else value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("schedule timestamps must include a timezone")
        return value


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    segment_id: UUID
    name: str
    objective_key: str
    channel: str
    starts_at: datetime | None
    ends_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime


class CampaignPage(BaseModel):
    items: list[CampaignRead]
    total: int
    limit: int
    offset: int


async def _require_permission(
    context: TenantSessionContext, permission_key: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Campaign action is not authorized for this organization scope")


async def _active_segment(
    context: TenantSessionContext, *, segment_id: UUID, organization_unit_id: UUID
) -> CRMProfileSegment:
    segment = await context.session.scalar(
        select(CRMProfileSegment).where(
            CRMProfileSegment.tenant_id == context.access.tenant_id,
            CRMProfileSegment.id == segment_id,
        )
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="CRM audience segment not found")
    if segment.organization_unit_id != organization_unit_id:
        raise HTTPException(status_code=422, detail="Campaign and segment must use the same organization scope")
    if not segment.is_active:
        raise HTTPException(status_code=409, detail="Campaigns require an active audience segment")
    await _require_permission(context, "crm.segment:view", organization_unit_id)
    return segment


def _audit(context: TenantSessionContext, campaign: CRMMarketingCampaign, action_key: str) -> None:
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key=action_key,
            target_type="crm_marketing_campaign",
            target_key=str(campaign.id),
            organization_unit_id=campaign.organization_unit_id,
            before_state=None,
            after_state={"status": campaign.status, "channel": campaign.channel},
            correlation_id=None,
        )
    )


@router.get("", response_model=CampaignPage, operation_id="listCRMMarketingCampaigns")
async def list_campaigns(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    status_filter: Literal["draft", "archived"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CampaignPage:
    filters = [
        CRMMarketingCampaign.tenant_id == context.access.tenant_id,
        CRMMarketingCampaign.organization_unit_id.in_(
            crm_scope_ids(context, permission_key="crm.campaign:view")
        ),
    ]
    if organization_unit_id is not None:
        filters.append(CRMMarketingCampaign.organization_unit_id == organization_unit_id)
    if status_filter is not None:
        filters.append(CRMMarketingCampaign.status == status_filter)
    total = int(await context.session.scalar(
        select(func.count()).select_from(CRMMarketingCampaign).where(*filters)
    ) or 0)
    campaigns = (await context.session.scalars(
        select(CRMMarketingCampaign).where(*filters)
        .order_by(CRMMarketingCampaign.updated_at.desc(), CRMMarketingCampaign.id)
        .limit(limit).offset(offset)
    )).all()
    return CampaignPage(
        items=[CampaignRead.model_validate(item) for item in campaigns],
        total=total, limit=limit, offset=offset,
    )


@router.post(
    "", response_model=CampaignRead, status_code=status.HTTP_201_CREATED,
    operation_id="createCRMMarketingCampaign",
)
async def create_campaign(
    payload: CampaignCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignRead:
    await _require_permission(context, "crm.campaign:manage", payload.organization_unit_id)
    await _active_segment(
        context, segment_id=payload.segment_id, organization_unit_id=payload.organization_unit_id
    )
    campaign = CRMMarketingCampaign(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id, segment_id=payload.segment_id,
        name=payload.name, objective_key=payload.objective_key, channel=payload.channel,
        starts_at=payload.starts_at, ends_at=payload.ends_at, status="draft",
    )
    context.session.add(campaign)
    await context.session.flush()
    _audit(context, campaign, "crm_marketing_campaign.created")
    await context.session.flush()
    return CampaignRead.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignRead, operation_id="updateCRMMarketingCampaign")
async def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignRead:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one campaign field is required")
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        ).with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="CRM campaign not found")
    await _require_permission(context, "crm.campaign:manage", campaign.organization_unit_id)
    if campaign.status != "draft":
        raise HTTPException(status_code=409, detail="Archived campaigns cannot be updated")
    if "segment_id" in changes:
        await _active_segment(
            context, segment_id=changes["segment_id"],
            organization_unit_id=campaign.organization_unit_id,
        )
    candidate_start = changes.get("starts_at", campaign.starts_at)
    candidate_end = changes.get("ends_at", campaign.ends_at)
    if candidate_start is not None and candidate_end is not None and candidate_start >= candidate_end:
        raise HTTPException(status_code=422, detail="starts_at must be earlier than ends_at")
    for key, value in changes.items():
        setattr(campaign, key, value)
    campaign.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit(context, campaign, "crm_marketing_campaign.updated")
    await context.session.flush()
    return CampaignRead.model_validate(campaign)


@router.post(
    "/{campaign_id}/archive", status_code=status.HTTP_204_NO_CONTENT,
    operation_id="archiveCRMMarketingCampaign",
)
async def archive_campaign(
    campaign_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        ).with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="CRM campaign not found")
    await _require_permission(context, "crm.campaign:manage", campaign.organization_unit_id)
    if campaign.status == "draft":
        campaign.status = "archived"
        campaign.updated_at = datetime.now(timezone.utc)
        await context.session.flush()
        _audit(context, campaign, "crm_marketing_campaign.archived")
        await context.session.flush()
