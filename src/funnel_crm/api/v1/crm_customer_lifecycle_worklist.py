"""Read-only, evidence-backed follow-up candidates for customer lifecycle review."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import AuditEvent, CRMCustomerActivity, CRMProfile
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/customer-lifecycle/follow-up-candidates",
    tags=["CRM customer lifecycle analytics"],
)


class LifecycleFollowUpCandidate(BaseModel):
    profile_id: UUID
    organization_unit_id: UUID
    display_name: str
    profile_kind: str
    current_lifecycle_stage: str
    latest_recorded_activity_at: datetime | None
    recorded_activity_count: int
    days_since_recorded_activity: int | None
    reason: str


class LifecycleFollowUpCandidatePage(BaseModel):
    as_of: datetime
    inactive_for_days: int
    inactivity_boundary: datetime
    lifecycle_stage_filter: str | None
    profile_kind_filter: str | None
    organization_unit_id: UUID | None
    total: int
    limit: int
    offset: int
    has_more: bool
    candidates: list[LifecycleFollowUpCandidate]
    basis: str
    contact_action_executed: bool
    causal_risk_inferred: bool


@router.get(
    "",
    response_model=LifecycleFollowUpCandidatePage,
    operation_id="listCustomerLifecycleFollowUpCandidates",
    summary="Review active profiles matching a manager-selected inactivity rule",
)
async def list_customer_lifecycle_follow_up_candidates(
    context: TenantSessionContext = Depends(require_tenant_session),
    inactive_for_days: int = Query(..., ge=1, le=365),
    as_of: datetime | None = None,
    lifecycle_stage: str | None = Query(default=None, min_length=1, max_length=80),
    profile_kind: str | None = Query(default=None, min_length=1, max_length=40),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> LifecycleFollowUpCandidatePage:
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    elif as_of.tzinfo is None or as_of.utcoffset() is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    else:
        as_of = as_of.astimezone(timezone.utc)
    if lifecycle_stage is not None and not lifecycle_stage.strip():
        raise HTTPException(status_code=422, detail="lifecycle_stage must not be blank")
    if profile_kind is not None and not profile_kind.strip():
        raise HTTPException(status_code=422, detail="profile_kind must not be blank")

    allowed_units = crm_scope_ids(context, permission_key="crm.profile:view")
    if organization_unit_id is not None and not await has_crm_permission(
        context,
        permission_key="crm.profile:view",
        organization_unit_id=organization_unit_id,
    ):
        raise HTTPException(status_code=403, detail="Customer lifecycle review is not authorized")

    tenant_id = context.access.tenant_id
    inactivity_boundary = as_of - timedelta(days=inactive_for_days)
    activity_summary = (
        select(
            CRMCustomerActivity.tenant_id.label("tenant_id"),
            CRMCustomerActivity.profile_id.label("profile_id"),
            func.max(CRMCustomerActivity.occurred_at).label("latest_activity_at"),
            func.count(CRMCustomerActivity.id).label("activity_count"),
        )
        .where(
            CRMCustomerActivity.tenant_id == tenant_id,
            CRMCustomerActivity.occurred_at <= as_of,
        )
        .group_by(CRMCustomerActivity.tenant_id, CRMCustomerActivity.profile_id)
        .subquery("lifecycle_activity_summary")
    )
    filters = [
        CRMProfile.tenant_id == tenant_id,
        CRMProfile.organization_unit_id.in_(allowed_units),
        CRMProfile.archived_at.is_(None),
        CRMProfile.merged_into_profile_id.is_(None),
        (activity_summary.c.latest_activity_at.is_(None)
         | (activity_summary.c.latest_activity_at < inactivity_boundary)),
    ]
    if organization_unit_id is not None:
        filters.append(CRMProfile.organization_unit_id == organization_unit_id)
    if lifecycle_stage is not None:
        filters.append(CRMProfile.lifecycle_stage == lifecycle_stage.strip())
    if profile_kind is not None:
        filters.append(CRMProfile.profile_kind == profile_kind.strip())

    candidate_query = (
        select(
            CRMProfile.id.label("profile_id"),
            CRMProfile.organization_unit_id,
            CRMProfile.display_name,
            CRMProfile.profile_kind,
            CRMProfile.lifecycle_stage,
            activity_summary.c.latest_activity_at,
            func.coalesce(activity_summary.c.activity_count, 0).label("activity_count"),
        )
        .outerjoin(
            activity_summary,
            (activity_summary.c.tenant_id == CRMProfile.tenant_id)
            & (activity_summary.c.profile_id == CRMProfile.id),
        )
        .where(*filters)
    )
    total = int(await context.session.scalar(
        select(func.count()).select_from(candidate_query.subquery())
    ) or 0)
    rows = (await context.session.execute(
        candidate_query.order_by(
            activity_summary.c.latest_activity_at.asc().nullsfirst(),
            CRMProfile.display_name,
            CRMProfile.id,
        ).limit(limit).offset(offset)
    )).all()

    candidates = []
    for row in rows:
        days_since = (
            (as_of - row.latest_activity_at).days
            if row.latest_activity_at is not None
            else None
        )
        candidates.append(LifecycleFollowUpCandidate(
            profile_id=row.profile_id,
            organization_unit_id=row.organization_unit_id,
            display_name=row.display_name,
            profile_kind=row.profile_kind,
            current_lifecycle_stage=row.lifecycle_stage,
            latest_recorded_activity_at=row.latest_activity_at,
            recorded_activity_count=int(row.activity_count),
            days_since_recorded_activity=days_since,
            reason=(
                "No linked activity is recorded in CRM"
                if row.latest_activity_at is None
                else "Latest linked activity is older than the selected inactivity boundary"
            ),
        ))

    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_customer_lifecycle.follow_up_candidates_viewed",
        target_type="crm_customer_lifecycle_follow_up_candidates",
        target_key=str(organization_unit_id or "authorized-scope"),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={
            "as_of": as_of.isoformat(),
            "inactive_for_days": inactive_for_days,
            "lifecycle_stage": lifecycle_stage,
            "profile_kind": profile_kind,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        correlation_id=None,
    ))
    await context.session.flush()

    return LifecycleFollowUpCandidatePage(
        as_of=as_of,
        inactive_for_days=inactive_for_days,
        inactivity_boundary=inactivity_boundary,
        lifecycle_stage_filter=lifecycle_stage,
        profile_kind_filter=profile_kind,
        organization_unit_id=organization_unit_id,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(candidates) < total,
        candidates=candidates,
        basis=("Candidates match only the caller-selected inactivity rule against recorded CRM activities and current active profiles. "
               "Missing activity means no linked activity is recorded in CRM; it does not prove that no interaction occurred."),
        contact_action_executed=False,
        causal_risk_inferred=False,
    )
