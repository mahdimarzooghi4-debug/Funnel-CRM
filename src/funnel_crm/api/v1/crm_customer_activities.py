"""Authorized read and idempotent synchronization API for CRM activities."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids
from funnel_crm.platform.models import AuditEvent, CRMCustomerActivity, CRMMarketingCampaign, CRMProfile
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/profiles", tags=["CRM customer activity"])


class CRMCustomerActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_product: str
    campaign_id: UUID | None
    activity_type: str
    channel: str
    source_record_id: str | None
    occurred_at: datetime
    created_at: datetime


class CRMCustomerActivityPage(BaseModel):
    items: list[CRMCustomerActivityRead]
    total: int
    limit: int
    offset: int


class CRMCustomerActivitySyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_event_id: UUID
    campaign_id: UUID | None = None
    activity_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    channel: Literal["phone", "store", "field", "other"]
    source_record_id: str | None = Field(default=None, max_length=200)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("source_record_id")
    @classmethod
    def normalize_source_record_id(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        if value == "":
            return None
        return value


class CRMCustomerActivitySyncReceipt(BaseModel):
    activity: CRMCustomerActivityRead
    duplicate: bool


@router.get(
    "/{profile_id}/activities",
    response_model=CRMCustomerActivityPage,
    operation_id="listCRMCustomerActivities",
    summary="List customer activities in the caller's authorized scope",
)
async def list_crm_customer_activities(
    profile_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CRMCustomerActivityPage:
    """Return only timeline entries whose profile is in the caller's view scope."""
    allowed_units = crm_scope_ids(context, permission_key="crm.profile:view")
    profile = await context.session.scalar(
        select(CRMProfile)
        .where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.id == profile_id,
            CRMProfile.organization_unit_id.in_(allowed_units),
        )
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CRM profile not found",
        )

    filters = [
        CRMCustomerActivity.tenant_id == context.access.tenant_id,
        CRMCustomerActivity.profile_id == profile_id,
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id.in_(allowed_units),
    ]
    total = int(
        await context.session.scalar(
            select(func.count())
            .select_from(CRMCustomerActivity)
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(*filters)
        )
        or 0
    )
    activities = (
        await context.session.scalars(
            select(CRMCustomerActivity)
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(*filters)
            .order_by(
                CRMCustomerActivity.occurred_at.desc(),
                CRMCustomerActivity.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="crm_profile.activities_viewed",
            target_type="crm_profile",
            target_key=str(profile_id),
            organization_unit_id=profile.organization_unit_id,
            before_state=None,
            after_state={
                "activity_count": len(activities),
                "total": total,
                "limit": limit,
                "offset": offset,
            },
            correlation_id=None,
        )
    )
    await context.session.flush()
    return CRMCustomerActivityPage(
        items=[CRMCustomerActivityRead.model_validate(item) for item in activities],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{profile_id}/activities/sync",
    response_model=CRMCustomerActivitySyncReceipt,
    status_code=status.HTTP_201_CREATED,
    operation_id="syncCRMCustomerActivity",
    summary="Record an offline field activity idempotently",
)
async def sync_crm_customer_activity(
    profile_id: UUID,
    payload: CRMCustomerActivitySyncRequest,
    response: Response,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMCustomerActivitySyncReceipt:
    """Persist one client-generated event ID; identical retries return the prior event."""
    tenant_id = context.access.tenant_id
    allowed_units = crm_scope_ids(context, permission_key="crm.profile:update")
    profile = await context.session.scalar(
        select(CRMProfile).where(
            CRMProfile.tenant_id == tenant_id,
            CRMProfile.id == profile_id,
            CRMProfile.organization_unit_id.in_(allowed_units),
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")
    if payload.campaign_id is not None:
        campaign_units = crm_scope_ids(context, permission_key="crm.campaign:view")
        campaign = await context.session.scalar(
            select(CRMMarketingCampaign).where(
                CRMMarketingCampaign.tenant_id == tenant_id,
                CRMMarketingCampaign.organization_unit_id == profile.organization_unit_id,
                CRMMarketingCampaign.organization_unit_id.in_(campaign_units),
                CRMMarketingCampaign.id == payload.campaign_id,
            )
        )
        if campaign is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM campaign not found")

    source_product = "funnel-crm"
    normalized = {
        "tenant_id": tenant_id,
        "profile_id": profile_id,
        "source_product": source_product,
        "source_event_id": payload.source_event_id,
        "campaign_id": payload.campaign_id,
        "activity_type": payload.activity_type,
        "channel": payload.channel,
        "source_record_id": payload.source_record_id,
        "occurred_at": payload.occurred_at,
    }
    inserted_id = await context.session.scalar(
        pg_insert(CRMCustomerActivity)
        .values(**normalized)
        .on_conflict_do_nothing(constraint="uq_crm_customer_activities_source_event")
        .returning(CRMCustomerActivity.id)
    )
    duplicate = inserted_id is None
    activity = await context.session.scalar(
        select(CRMCustomerActivity).where(
            CRMCustomerActivity.tenant_id == tenant_id,
            CRMCustomerActivity.source_product == source_product,
            CRMCustomerActivity.source_event_id == payload.source_event_id,
        )
    )
    if activity is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Activity sync could not be confirmed; retry with the same event ID")
    if duplicate:
        matches = all(getattr(activity, key) == value for key, value in normalized.items())
        if not matches:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Event ID already exists with different activity data")
        response.status_code = status.HTTP_200_OK
    else:
        context.session.add(AuditEvent(
            tenant_id=tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="crm_profile.activity_recorded",
            target_type="crm_profile",
            target_key=str(profile_id),
            organization_unit_id=profile.organization_unit_id,
            before_state=None,
            after_state={
                "source_event_id": str(payload.source_event_id),
                "activity_type": payload.activity_type,
                "channel": payload.channel,
                "occurred_at": payload.occurred_at.isoformat(),
                "sync_source": "offline-capable-crm-client",
            },
            correlation_id=None,
        ))
    await context.session.flush()
    return CRMCustomerActivitySyncReceipt(
        activity=CRMCustomerActivityRead.model_validate(activity),
        duplicate=duplicate,
    )
