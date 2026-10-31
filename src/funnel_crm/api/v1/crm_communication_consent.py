"""Append-only customer communication decisions and fail-closed eligibility reads."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.consent_product_sync import enqueue_consent_change_for_products
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import CRMCommunicationConsentEvent, CRMProfile
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/profiles/{profile_id}",
    tags=["CRM communication consent"],
)

_CHANNEL_PATTERN = r"^(email|phone|postal_address|social_handle|website)$"
_PURPOSE_PATTERN = r"^[a-z][a-z0-9_.-]{0,79}$"


class CommunicationConsentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose_key: str = Field(pattern=_PURPOSE_PATTERN)
    channel: str = Field(pattern=_CHANNEL_PATTERN)
    decision: Literal["granted", "withdrawn"]
    policy_version: str = Field(min_length=1, max_length=64)

    @field_validator("policy_version")
    @classmethod
    def normalize_policy_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("policy_version must not be blank")
        return value


class CommunicationConsentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    purpose_key: str
    channel: str
    decision: str
    policy_version: str
    source_product: str | None
    source_event_id: UUID | None
    decision_at: datetime
    recorded_at: datetime


class CommunicationConsentPage(BaseModel):
    items: list[CommunicationConsentRead]


class CommunicationEligibility(BaseModel):
    purpose_key: str
    channel: str
    allowed: bool
    decision: str | None
    decision_at: datetime | None
    recorded_at: datetime | None


async def _authorized_profile(
    context: TenantSessionContext,
    *,
    profile_id: UUID,
    action_permission: str,
) -> CRMProfile:
    profile = await context.session.scalar(
        select(CRMProfile).where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.id == profile_id,
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="CRM profile not found")

    can_view_profile = await has_crm_permission(
        context,
        permission_key="crm.profile:view",
        organization_unit_id=profile.organization_unit_id,
    )
    can_act = await has_crm_permission(
        context,
        permission_key=action_permission,
        organization_unit_id=profile.organization_unit_id,
    )
    if not can_view_profile or not can_act:
        raise HTTPException(status_code=403, detail="CRM communication consent access denied")
    return profile


@router.get(
    "/communication-consents",
    response_model=CommunicationConsentPage,
    operation_id="listCRMCommunicationConsentEvents",
    summary="Read communication decision history",
)
async def list_communication_consents(
    profile_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CommunicationConsentPage:
    profile = await _authorized_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.communication_consent:view",
    )
    rows = (
        await context.session.scalars(
            select(CRMCommunicationConsentEvent)
            .where(
                CRMCommunicationConsentEvent.tenant_id == context.access.tenant_id,
                CRMCommunicationConsentEvent.profile_id == profile.id,
            )
            .order_by(
                CRMCommunicationConsentEvent.recorded_at.desc(),
                CRMCommunicationConsentEvent.id.desc(),
            )
            .limit(limit)
        )
    ).all()
    return CommunicationConsentPage(items=list(rows))


@router.post(
    "/communication-consents",
    response_model=CommunicationConsentRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="recordCRMCommunicationConsentEvent",
    summary="Record an explicit communication decision",
)
async def record_communication_consent(
    profile_id: UUID,
    payload: CommunicationConsentCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CommunicationConsentRead:
    profile = await _authorized_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.communication_consent:record",
    )
    event = CRMCommunicationConsentEvent(
        tenant_id=context.access.tenant_id,
        profile_id=profile.id,
        purpose_key=payload.purpose_key,
        channel=payload.channel,
        decision=payload.decision,
        policy_version=payload.policy_version,
    )
    context.session.add(event)
    await context.session.flush()
    await enqueue_consent_change_for_products(
        context.session,
        tenant_id=context.access.tenant_id,
        profile_id=profile.id,
        consent_event_id=event.id,
        purpose_key=event.purpose_key,
        channel=event.channel,
        decision=event.decision,
        policy_version=event.policy_version,
        decision_at=event.decision_at,
        origin_product=event.source_product,
        source_event_id=event.source_event_id,
    )
    return CommunicationConsentRead.model_validate(event)


@router.get(
    "/communication-eligibility",
    response_model=CommunicationEligibility,
    operation_id="getCRMCommunicationEligibility",
    summary="Check explicit communication permission for one purpose and channel",
)
async def get_communication_eligibility(
    profile_id: UUID,
    purpose_key: str = Query(pattern=_PURPOSE_PATTERN),
    channel: str = Query(pattern=_CHANNEL_PATTERN),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CommunicationEligibility:
    profile = await _authorized_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.communication_consent:view",
    )
    latest = await context.session.scalar(
        select(CRMCommunicationConsentEvent)
        .where(
            CRMCommunicationConsentEvent.tenant_id == context.access.tenant_id,
            CRMCommunicationConsentEvent.profile_id == profile.id,
            CRMCommunicationConsentEvent.purpose_key == purpose_key,
            CRMCommunicationConsentEvent.channel == channel,
        )
        .order_by(
            CRMCommunicationConsentEvent.decision_at.desc(),
            CRMCommunicationConsentEvent.recorded_at.desc(),
            CRMCommunicationConsentEvent.id.desc(),
        )
        .limit(1)
    )
    return CommunicationEligibility(
        purpose_key=purpose_key,
        channel=channel,
        allowed=latest is not None and latest.decision == "granted",
        decision=latest.decision if latest else None,
        decision_at=latest.decision_at if latest else None,
        recorded_at=latest.recorded_at if latest else None,
    )
