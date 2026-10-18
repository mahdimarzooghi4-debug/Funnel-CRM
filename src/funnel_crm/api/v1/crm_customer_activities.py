"""Authorized read API for the CRM customer activity timeline."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids
from funnel_crm.platform.models import AuditEvent, CRMCustomerActivity, CRMProfile
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
