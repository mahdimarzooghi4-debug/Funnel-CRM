"""Aggregate customer lifecycle cohorts with recorded CRM interactions and outcomes."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, tuple_

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerActivity,
    CRMOpportunity,
    CRMProductCommerceEvent,
    CRMProfile,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/analytics/customer-lifecycle",
    tags=["CRM customer lifecycle analytics"],
)


class LifecycleCommerceCurrencyMetric(BaseModel):
    currency: str
    paid_event_count: int
    paid_order_count: int
    paid_profile_count: int
    paid_amount: Decimal
    refunded_event_count: int
    refunded_order_count: int
    refunded_profile_count: int
    refunded_amount: Decimal


class CustomerLifecycleStageMetric(BaseModel):
    profile_kind: str
    current_lifecycle_stage: str
    current_profile_count: int
    profiles_with_activity: int
    recorded_activity_count: int
    profiles_with_opportunity: int
    opportunity_count: int
    profiles_with_paid_event: int
    profiles_with_refund_event: int
    commerce_by_currency: list[LifecycleCommerceCurrencyMetric]


class CustomerLifecycleAnalytics(BaseModel):
    period_start: date
    period_end: date
    generated_at: datetime
    organization_unit_id: UUID | None
    total_cohort_count: int
    has_more: bool
    cohorts: list[CustomerLifecycleStageMetric]
    cohort_basis: str
    interaction_basis: str
    causal_attribution_applied: bool
    currency_conversion_applied: bool


@router.get(
    "",
    response_model=CustomerLifecycleAnalytics,
    operation_id="getCustomerLifecycleAnalytics",
)
async def get_customer_lifecycle_analytics(
    period_start: date = Query(...),
    period_end: date = Query(...),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CustomerLifecycleAnalytics:
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="period_start must not be after period_end")
    if (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="Reports are limited to 366 calendar days")

    permissions = (
        ("crm.profile:view", "lifecycle_profile_scope"),
        ("crm.opportunity:view", "lifecycle_opportunity_scope"),
        ("crm.commerce_event:view", "lifecycle_commerce_scope"),
    )
    scopes = {
        permission: crm_scope_ids(context, permission_key=permission, cte_name=name)
        for permission, name in permissions
    }
    if organization_unit_id is not None:
        for permission, _ in permissions:
            if not await has_crm_permission(
                context, permission_key=permission, organization_unit_id=organization_unit_id
            ):
                raise HTTPException(status_code=403, detail="Customer lifecycle analytics is not authorized")

    tenant_id = context.access.tenant_id
    profile_filters = [
        CRMProfile.tenant_id == tenant_id,
        CRMProfile.archived_at.is_(None),
        CRMProfile.merged_into_profile_id.is_(None),
        CRMProfile.organization_unit_id.in_(scopes["crm.profile:view"]),
    ]
    if organization_unit_id is not None:
        profile_filters.append(CRMProfile.organization_unit_id == organization_unit_id)
    grouped_profiles = (
        select(
            CRMProfile.profile_kind.label("profile_kind"),
            CRMProfile.lifecycle_stage.label("lifecycle_stage"),
            func.count(CRMProfile.id).label("profile_count"),
        )
        .where(*profile_filters)
        .group_by(CRMProfile.profile_kind, CRMProfile.lifecycle_stage)
    )
    total_cohort_count = int(await context.session.scalar(
        select(func.count()).select_from(grouped_profiles.subquery())
    ) or 0)
    profile_rows = (await context.session.execute(
        grouped_profiles.order_by(
            func.count(CRMProfile.id).desc(), CRMProfile.profile_kind, CRMProfile.lifecycle_stage
        ).limit(limit).offset(offset)
    )).all()
    keys = [(row.profile_kind, row.lifecycle_stage) for row in profile_rows]

    stage_state: dict[tuple[str, str], dict] = {
        key: {
            "profile_count": int(row.profile_count),
            "profiles_with_activity": 0,
            "recorded_activity_count": 0,
            "profiles_with_opportunity": 0,
            "opportunity_count": 0,
            "profiles_with_paid_event": 0,
            "profiles_with_refund_event": 0,
            "commerce": {},
        }
        for key, row in zip(keys, profile_rows, strict=True)
    }
    start_at = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    end_exclusive = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    key_filter = tuple_(CRMProfile.profile_kind, CRMProfile.lifecycle_stage).in_(keys)

    if keys:
        activity_rows = (await context.session.execute(
            select(
                CRMProfile.profile_kind,
                CRMProfile.lifecycle_stage,
                func.count(CRMCustomerActivity.id).label("activity_count"),
                func.count(func.distinct(CRMCustomerActivity.profile_id)).label("profile_count"),
            )
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMCustomerActivity.tenant_id)
                & (CRMProfile.id == CRMCustomerActivity.profile_id),
            )
            .where(
                CRMCustomerActivity.tenant_id == tenant_id,
                CRMCustomerActivity.occurred_at >= start_at,
                CRMCustomerActivity.occurred_at < end_exclusive,
                *profile_filters,
                key_filter,
            )
            .group_by(CRMProfile.profile_kind, CRMProfile.lifecycle_stage)
        )).all()
        for row in activity_rows:
            state = stage_state[(row.profile_kind, row.lifecycle_stage)]
            state["profiles_with_activity"] = int(row.profile_count)
            state["recorded_activity_count"] = int(row.activity_count)

        opportunity_filters = [
            CRMOpportunity.tenant_id == tenant_id,
            CRMOpportunity.organization_unit_id.in_(scopes["crm.opportunity:view"]),
            CRMOpportunity.created_at >= start_at,
            CRMOpportunity.created_at < end_exclusive,
            CRMOpportunity.profile_id.is_not(None),
            *profile_filters,
            key_filter,
        ]
        if organization_unit_id is not None:
            opportunity_filters.append(CRMOpportunity.organization_unit_id == organization_unit_id)
        opportunity_rows = (await context.session.execute(
            select(
                CRMProfile.profile_kind,
                CRMProfile.lifecycle_stage,
                func.count(CRMOpportunity.id).label("opportunity_count"),
                func.count(func.distinct(CRMOpportunity.profile_id)).label("profile_count"),
            )
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMOpportunity.tenant_id)
                & (CRMProfile.id == CRMOpportunity.profile_id)
                & (CRMProfile.organization_unit_id == CRMOpportunity.organization_unit_id),
            )
            .where(*opportunity_filters)
            .group_by(CRMProfile.profile_kind, CRMProfile.lifecycle_stage)
        )).all()
        for row in opportunity_rows:
            state = stage_state[(row.profile_kind, row.lifecycle_stage)]
            state["profiles_with_opportunity"] = int(row.profile_count)
            state["opportunity_count"] = int(row.opportunity_count)

        commerce_filters = [
            CRMProductCommerceEvent.tenant_id == tenant_id,
            CRMProductCommerceEvent.organization_unit_id.in_(scopes["crm.commerce_event:view"]),
            CRMProductCommerceEvent.occurred_at >= start_at,
            CRMProductCommerceEvent.occurred_at < end_exclusive,
            CRMProductCommerceEvent.profile_id.is_not(None),
            *profile_filters,
            key_filter,
        ]
        if organization_unit_id is not None:
            commerce_filters.append(CRMProductCommerceEvent.organization_unit_id == organization_unit_id)
        commerce_rows = (await context.session.execute(
            select(
                CRMProfile.profile_kind,
                CRMProfile.lifecycle_stage,
                CRMProductCommerceEvent.event_kind,
                CRMProductCommerceEvent.currency,
                func.count(CRMProductCommerceEvent.id).label("event_count"),
                func.count(func.distinct(tuple_(
                    CRMProductCommerceEvent.source_product,
                    CRMProductCommerceEvent.order_reference,
                ))).label("order_count"),
                func.count(func.distinct(CRMProductCommerceEvent.profile_id)).label("profile_count"),
                func.sum(CRMProductCommerceEvent.amount).label("amount_total"),
            )
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMProductCommerceEvent.tenant_id)
                & (CRMProfile.id == CRMProductCommerceEvent.profile_id)
                & (CRMProfile.organization_unit_id == CRMProductCommerceEvent.organization_unit_id),
            )
            .where(*commerce_filters)
            .group_by(
                CRMProfile.profile_kind, CRMProfile.lifecycle_stage,
                CRMProductCommerceEvent.event_kind, CRMProductCommerceEvent.currency,
            )
        )).all()
        commerce_profile_rows = (await context.session.execute(
            select(
                CRMProfile.profile_kind,
                CRMProfile.lifecycle_stage,
                CRMProductCommerceEvent.event_kind,
                func.count(func.distinct(CRMProductCommerceEvent.profile_id)).label("profile_count"),
            )
            .join(
                CRMProfile,
                (CRMProfile.tenant_id == CRMProductCommerceEvent.tenant_id)
                & (CRMProfile.id == CRMProductCommerceEvent.profile_id)
                & (CRMProfile.organization_unit_id == CRMProductCommerceEvent.organization_unit_id),
            )
            .where(*commerce_filters)
            .group_by(CRMProfile.profile_kind, CRMProfile.lifecycle_stage, CRMProductCommerceEvent.event_kind)
        )).all()
        for row in commerce_profile_rows:
            state = stage_state[(row.profile_kind, row.lifecycle_stage)]
            state[f"profiles_with_{row.event_kind}_event"] = int(row.profile_count)
        for row in commerce_rows:
            state = stage_state[(row.profile_kind, row.lifecycle_stage)]
            currency_state = state["commerce"].setdefault(row.currency, {
                "paid_event_count": 0, "paid_order_count": 0, "paid_profile_count": 0,
                "paid_amount": Decimal("0"), "refunded_event_count": 0,
                "refunded_order_count": 0, "refunded_profile_count": 0,
                "refunded_amount": Decimal("0"),
            })
            prefix = "paid" if row.event_kind == "paid" else "refunded"
            currency_state[f"{prefix}_event_count"] = int(row.event_count)
            currency_state[f"{prefix}_order_count"] = int(row.order_count)
            currency_state[f"{prefix}_profile_count"] = int(row.profile_count)
            currency_state[f"{prefix}_amount"] = row.amount_total or Decimal("0")

    cohorts = []
    for key in keys:
        state = stage_state[key]
        cohorts.append(CustomerLifecycleStageMetric(
            profile_kind=key[0],
            current_lifecycle_stage=key[1],
            current_profile_count=state["profile_count"],
            profiles_with_activity=state["profiles_with_activity"],
            recorded_activity_count=state["recorded_activity_count"],
            profiles_with_opportunity=state["profiles_with_opportunity"],
            opportunity_count=state["opportunity_count"],
            profiles_with_paid_event=state.get("profiles_with_paid_event", 0),
            profiles_with_refund_event=state.get("profiles_with_refunded_event", 0),
            commerce_by_currency=[
                LifecycleCommerceCurrencyMetric(currency=currency, **values)
                for currency, values in sorted(state["commerce"].items())
            ],
        ))

    context.session.add(AuditEvent(
        tenant_id=tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_customer_lifecycle.analytics_viewed",
        target_type="crm_customer_lifecycle_analytics",
        target_key=str(organization_unit_id or "authorized-scope"),
        organization_unit_id=organization_unit_id,
        before_state=None,
        after_state={"period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
                     "total_cohort_count": total_cohort_count, "returned_cohort_count": len(cohorts),
                     "limit": limit, "offset": offset},
        correlation_id=None,
    ))
    await context.session.flush()
    return CustomerLifecycleAnalytics(
        period_start=period_start,
        period_end=period_end,
        generated_at=datetime.now(timezone.utc),
        organization_unit_id=organization_unit_id,
        total_cohort_count=total_cohort_count,
        has_more=offset + len(cohorts) < total_cohort_count,
        cohorts=cohorts,
        cohort_basis="Cohorts use each active profile's current lifecycle stage and profile kind as of report generation.",
        interaction_basis=("Activities, opportunities, paid events, and refunds are included only when linked to an authorized active profile "
                           "and recorded within the selected period. These observed associations do not establish causality."),
        causal_attribution_applied=False,
        currency_conversion_applied=False,
    )
