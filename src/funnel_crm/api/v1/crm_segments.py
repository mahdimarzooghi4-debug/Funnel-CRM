"""Tenant- and organization-scoped saved customer audience segments."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import exists, func, not_, or_, select
from sqlalchemy.orm import aliased

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCommunicationConsentEvent,
    CRMContactPoint,
    CRMCustomerActivity,
    CRMProfile,
    CRMProfileSegment,
    OrganizationUnit,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/segments", tags=["CRM audience segments"])


class CRMProfileActivityCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_types: list[str] | None = Field(default=None, max_length=20)
    channels: list[
        Literal["online", "phone", "store", "field", "support", "campaign", "other"]
    ] | None = Field(default=None, max_length=7)
    within_last_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("activity_types")
    @classmethod
    def validate_activity_types(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if (
            not normalized
            or any(
                not value
                or len(value) > 80
                or not value[0].islower()
                or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_.-" for ch in value)
                for value in normalized
            )
            or len(normalized) != len(set(normalized))
        ):
            raise ValueError("activity_types must contain unique stable activity keys")
        return normalized

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if not values or len(values) != len(set(values)):
            raise ValueError("channels must be a non-empty list without duplicates")
        return values

    @model_validator(mode="after")
    def require_activity_filter(self) -> "CRMProfileActivityCriteria":
        if (
            self.activity_types is None
            and self.channels is None
            and self.within_last_days is None
        ):
            raise ValueError("At least one activity filter is required")
        return self


class CRMProfileSegmentCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_kinds: list[Literal["person", "organization"]] | None = Field(default=None, max_length=2)
    lifecycle_stages: list[str] | None = Field(default=None, max_length=20)
    activity: CRMProfileActivityCriteria | None = None
    include_segment_ids: list[UUID] | None = Field(default=None, max_length=20)
    exclude_segment_ids: list[UUID] | None = Field(default=None, max_length=20)

    @field_validator("include_segment_ids", "exclude_segment_ids")
    @classmethod
    def validate_segment_references(cls, values: list[UUID] | None) -> list[UUID] | None:
        if values is not None and (not values or len(values) != len(set(values))):
            raise ValueError("segment references must be non-empty and unique")
        return values

    @field_validator("profile_kinds")
    @classmethod
    def validate_profile_kinds(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if not values or len(values) != len(set(values)):
            raise ValueError("profile_kinds must be a non-empty list without duplicates")
        return values

    @field_validator("lifecycle_stages")
    @classmethod
    def validate_lifecycle_stages(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if (
            not normalized
            or any(not value or len(value) > 80 for value in normalized)
            or len(normalized) != len(set(normalized))
        ):
            raise ValueError("lifecycle_stages must contain unique non-empty values up to 80 characters")
        return normalized

    @model_validator(mode="after")
    def require_filter(self) -> "CRMProfileSegmentCriteria":
        if (
            self.profile_kinds is None
            and self.lifecycle_stages is None
            and self.activity is None
            and self.include_segment_ids is None
        ):
            raise ValueError("At least one profile, activity, or included segment filter is required")
        if self.include_segment_ids and self.exclude_segment_ids:
            if set(self.include_segment_ids) & set(self.exclude_segment_ids):
                raise ValueError("a segment cannot be both included and excluded")
        return self

class CRMProfileSegmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    name: str = Field(min_length=1, max_length=160)
    criteria: CRMProfileSegmentCriteria

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must contain a non-whitespace character")
        return value


class CRMProfileSegmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    criteria: CRMProfileSegmentCriteria | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("explicit null is not allowed")
        value = value.strip()
        if not value:
            raise ValueError("name must contain a non-whitespace character")
        return value


class CRMProfileSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    name: str
    criteria: CRMProfileSegmentCriteria
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CRMProfileSegmentPage(BaseModel):
    items: list[CRMProfileSegmentRead]
    total: int
    limit: int
    offset: int


class CRMProfileSegmentMember(BaseModel):
    id: UUID
    profile_kind: str
    display_name: str
    lifecycle_stage: str


class CRMProfileSegmentPreview(BaseModel):
    segment_id: UUID
    total: int
    items: list[CRMProfileSegmentMember]
    limit: int
    offset: int

class CRMProfileSegmentChannelReach(BaseModel):
    segment_id: UUID
    purpose_key: str
    channel: str
    total_profiles: int
    profiles_with_contact: int
    profiles_with_verified_contact: int
    profiles_with_granted_consent: int
    eligible_profiles: int
    withdrawn_consent_profiles: int
    missing_or_withdrawn_consent_profiles: int
    eligibility_basis: str


def _criteria_filters(
    criteria: CRMProfileSegmentCriteria,
    *,
    tenant_id: UUID,
    segment_units,
    profile_scope,
) -> list[object]:
    filters: list[object] = [
        CRMProfile.tenant_id == tenant_id,
        CRMProfile.organization_unit_id.in_(segment_units),
        CRMProfile.organization_unit_id.in_(profile_scope),
        CRMProfile.merged_into_profile_id.is_(None),
        CRMProfile.archived_at.is_(None),
    ]
    if criteria.profile_kinds is not None:
        filters.append(CRMProfile.profile_kind.in_(criteria.profile_kinds))
    if criteria.lifecycle_stages is not None:
        filters.append(CRMProfile.lifecycle_stage.in_(criteria.lifecycle_stages))
    if criteria.activity is not None:
        activity_filters = [
            CRMCustomerActivity.tenant_id == tenant_id,
            CRMCustomerActivity.profile_id == CRMProfile.id,
        ]
        if criteria.activity.activity_types is not None:
            activity_filters.append(CRMCustomerActivity.activity_type.in_(criteria.activity.activity_types))
        if criteria.activity.channels is not None:
            activity_filters.append(CRMCustomerActivity.channel.in_(criteria.activity.channels))
        if criteria.activity.within_last_days is not None:
            activity_filters.append(
                CRMCustomerActivity.occurred_at >= datetime.now(timezone.utc) - timedelta(days=criteria.activity.within_last_days)
            )
        filters.append(exists(select(1).where(*activity_filters)))
    return filters


async def _validate_segment_references(
    context: TenantSessionContext,
    *,
    organization_unit_id: UUID,
    criteria: CRMProfileSegmentCriteria,
    current_segment_id: UUID | None = None,
) -> None:
    references = set(criteria.include_segment_ids or []) | set(criteria.exclude_segment_ids or [])
    if current_segment_id is not None and current_segment_id in references:
        raise HTTPException(status_code=422, detail="A segment cannot reference itself")
    if not references:
        return
    rows = (await context.session.scalars(
        select(CRMProfileSegment).where(
            CRMProfileSegment.tenant_id == context.access.tenant_id,
            CRMProfileSegment.organization_unit_id == organization_unit_id,
            CRMProfileSegment.id.in_(references),
            CRMProfileSegment.is_active.is_(True),
        )
    )).all()
    if len(rows) != len(references):
        raise HTTPException(status_code=422, detail="Referenced segments must be active and in the same organization scope")
    if any(
        row.criteria.get("include_segment_ids") or row.criteria.get("exclude_segment_ids")
        for row in rows
    ):
        raise HTTPException(status_code=422, detail="Nested segment composition is not supported")


async def _require_permission(
    context: TenantSessionContext,
    *,
    permission_key: str,
    organization_unit_id: UUID,
) -> None:
    if not await has_crm_permission(
        context,
        permission_key=permission_key,
        organization_unit_id=organization_unit_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CRM segment action is not authorized for this organization scope",
        )


def _audit(
    context: TenantSessionContext,
    *,
    action_key: str,
    segment: CRMProfileSegment,
    after_state: dict[str, object],
) -> None:
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key=action_key,
            target_type="crm_profile_segment",
            target_key=str(segment.id),
            organization_unit_id=segment.organization_unit_id,
            before_state=None,
            after_state=after_state,
            correlation_id=None,
        )
    )


@router.get(
    "",
    response_model=CRMProfileSegmentPage,
    operation_id="listCRMProfileSegments",
    summary="List active audience segments in the caller's scope",
)
async def list_crm_profile_segments(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CRMProfileSegmentPage:
    filters = [
        CRMProfileSegment.tenant_id == context.access.tenant_id,
        CRMProfileSegment.organization_unit_id.in_(
            crm_scope_ids(context, permission_key="crm.segment:view")
        ),
        CRMProfileSegment.is_active.is_(True),
    ]
    if organization_unit_id is not None:
        filters.append(CRMProfileSegment.organization_unit_id == organization_unit_id)
    total = await context.session.scalar(
        select(func.count()).select_from(CRMProfileSegment).where(*filters)
    )
    segments = (
        await context.session.scalars(
            select(CRMProfileSegment)
            .where(*filters)
            .order_by(CRMProfileSegment.name, CRMProfileSegment.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return CRMProfileSegmentPage(
        items=[CRMProfileSegmentRead.model_validate(segment) for segment in segments],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=CRMProfileSegmentRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCRMProfileSegment",
    summary="Save a dynamic customer audience segment",
)
async def create_crm_profile_segment(
    payload: CRMProfileSegmentCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMProfileSegmentRead:
    await _require_permission(
        context,
        permission_key="crm.segment:manage",
        organization_unit_id=payload.organization_unit_id,
    )
    await _validate_segment_references(
        context, organization_unit_id=payload.organization_unit_id, criteria=payload.criteria
    )
    segment = CRMProfileSegment(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        name=payload.name,
        criteria=payload.criteria.model_dump(exclude_none=True),
        is_active=True,
    )
    context.session.add(segment)
    await context.session.flush()
    _audit(
        context,
        action_key="crm_profile_segment.created",
        segment=segment,
        after_state={"criteria_keys": sorted(segment.criteria), "is_active": True},
    )
    await context.session.flush()
    return CRMProfileSegmentRead.model_validate(segment)


@router.patch(
    "/{segment_id}",
    response_model=CRMProfileSegmentRead,
    operation_id="updateCRMProfileSegment",
    summary="Update a saved customer audience segment",
)
async def update_crm_profile_segment(
    segment_id: UUID,
    payload: CRMProfileSegmentUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMProfileSegmentRead:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one segment field is required")
    segment = await context.session.scalar(
        select(CRMProfileSegment)
        .where(
            CRMProfileSegment.tenant_id == context.access.tenant_id,
            CRMProfileSegment.id == segment_id,
        )
        .with_for_update()
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="CRM segment not found")
    await _require_permission(
        context,
        permission_key="crm.segment:manage",
        organization_unit_id=segment.organization_unit_id,
    )
    if not segment.is_active:
        raise HTTPException(status_code=409, detail="Inactive CRM segments cannot be updated")
    if "criteria" in changes:
        await _validate_segment_references(
            context,
            organization_unit_id=segment.organization_unit_id,
            criteria=payload.criteria,
            current_segment_id=segment.id,
        )
    if "name" in changes:
        segment.name = changes["name"]
    if "criteria" in changes:
        criteria = changes["criteria"]
        if criteria is None:
            raise HTTPException(status_code=422, detail="criteria cannot be null")
        segment.criteria = criteria
    segment.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit(
        context,
        action_key="crm_profile_segment.updated",
        segment=segment,
        after_state={"criteria_keys": sorted(segment.criteria), "is_active": True},
    )
    await context.session.flush()
    return CRMProfileSegmentRead.model_validate(segment)


@router.post(
    "/{segment_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deactivateCRMProfileSegment",
    summary="Deactivate a saved customer audience segment",
)
async def deactivate_crm_profile_segment(
    segment_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    segment = await context.session.scalar(
        select(CRMProfileSegment)
        .where(
            CRMProfileSegment.tenant_id == context.access.tenant_id,
            CRMProfileSegment.id == segment_id,
        )
        .with_for_update()
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="CRM segment not found")
    await _require_permission(
        context,
        permission_key="crm.segment:manage",
        organization_unit_id=segment.organization_unit_id,
    )
    if segment.is_active:
        dependent = await context.session.scalar(
            select(CRMProfileSegment.id).where(
                CRMProfileSegment.tenant_id == context.access.tenant_id,
                CRMProfileSegment.organization_unit_id == segment.organization_unit_id,
                CRMProfileSegment.is_active.is_(True),
                CRMProfileSegment.id != segment.id,
                or_(
                    CRMProfileSegment.criteria.contains({"include_segment_ids": [str(segment.id)]}),
                    CRMProfileSegment.criteria.contains({"exclude_segment_ids": [str(segment.id)]}),
                ),
            ).limit(1)
        )
        if dependent is not None:
            raise HTTPException(status_code=409, detail="Segment is referenced by another active segment")
        segment.is_active = False
        segment.updated_at = datetime.now(timezone.utc)
        await context.session.flush()
        _audit(
            context,
            action_key="crm_profile_segment.deactivated",
            segment=segment,
            after_state={"is_active": False},
        )
        await context.session.flush()


async def _segment_member_filters(
    context: TenantSessionContext,
    segment: CRMProfileSegment,
) -> list[object]:
    segment_units = (
        select(OrganizationUnit.id.label("id"))
        .where(
            OrganizationUnit.tenant_id == context.access.tenant_id,
            OrganizationUnit.id == segment.organization_unit_id,
        )
        .cte("crm_segment_units", recursive=True)
    )
    child_unit = aliased(OrganizationUnit)
    segment_units = segment_units.union(
        select(child_unit.id)
        .join(segment_units, child_unit.parent_id == segment_units.c.id)
        .where(child_unit.tenant_id == context.access.tenant_id)
    )
    criteria = CRMProfileSegmentCriteria.model_validate(segment.criteria)
    profile_scope = crm_scope_ids(
        context, permission_key="crm.profile:view", cte_name="crm_segment_profile_scope"
    )
    base_filters = _criteria_filters(
        criteria, tenant_id=context.access.tenant_id,
        segment_units=segment_units, profile_scope=profile_scope,
    )
    has_base_filter = any((
        criteria.profile_kinds is not None,
        criteria.lifecycle_stages is not None,
        criteria.activity is not None,
    ))
    include_predicates = []
    if has_base_filter:
        include_predicates.append(select(CRMProfile.id).where(*base_filters))
    references = set(criteria.include_segment_ids or []) | set(criteria.exclude_segment_ids or [])
    referenced_segments = []
    if references:
        referenced_segments = (await context.session.scalars(
            select(CRMProfileSegment).where(
                CRMProfileSegment.tenant_id == context.access.tenant_id,
                CRMProfileSegment.organization_unit_id == segment.organization_unit_id,
                CRMProfileSegment.id.in_(references),
                CRMProfileSegment.is_active.is_(True),
            )
        )).all()
        if len(referenced_segments) != len(references):
            raise HTTPException(status_code=409, detail="A referenced segment is no longer active")
    exclude_predicates = []
    for referenced in referenced_segments:
        referenced_criteria = CRMProfileSegmentCriteria.model_validate(referenced.criteria)
        referenced_query = select(CRMProfile.id).where(*_criteria_filters(
            referenced_criteria, tenant_id=context.access.tenant_id,
            segment_units=segment_units, profile_scope=profile_scope,
        ))
        if referenced.id in (criteria.include_segment_ids or []):
            include_predicates.append(referenced_query)
        if referenced.id in (criteria.exclude_segment_ids or []):
            exclude_predicates.append(referenced_query)
    if not include_predicates:
        raise HTTPException(status_code=422, detail="At least one included segment or profile filter is required")
    membership = (
        CRMProfile.id.in_(include_predicates[0])
        if len(include_predicates) == 1
        else or_(*[CRMProfile.id.in_(query) for query in include_predicates])
    )
    filters: list[object] = [
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id.in_(segment_units),
        CRMProfile.organization_unit_id.in_(profile_scope),
        CRMProfile.merged_into_profile_id.is_(None),
        CRMProfile.archived_at.is_(None),
        membership,
    ]
    filters.extend(not_(CRMProfile.id.in_(query)) for query in exclude_predicates)
    return filters


async def _load_active_segment(
    context: TenantSessionContext,
    segment_id: UUID,
) -> CRMProfileSegment:
    segment = await context.session.scalar(
        select(CRMProfileSegment).where(
            CRMProfileSegment.tenant_id == context.access.tenant_id,
            CRMProfileSegment.id == segment_id,
            CRMProfileSegment.organization_unit_id.in_(
                crm_scope_ids(context, permission_key="crm.segment:view")
            ),
        )
    )
    if segment is None:
        raise HTTPException(status_code=404, detail="CRM segment not found")
    if not segment.is_active:
        raise HTTPException(status_code=409, detail="Inactive CRM segments cannot be previewed")
    await _require_permission(
        context, permission_key="crm.profile:view",
        organization_unit_id=segment.organization_unit_id,
    )
    return segment


@router.get(
    "/{segment_id}/reach",
    response_model=CRMProfileSegmentChannelReach,
    operation_id="reviewCRMProfileSegmentChannelReach",
    summary="Estimate consent-eligible audience reach for one channel",
)
async def review_crm_profile_segment_channel_reach(
    segment_id: UUID,
    purpose_key: str = Query(pattern=r"^[a-z][a-z0-9_.-]{0,79}$"),
    channel: Literal["email", "phone", "postal_address", "social_handle", "website"],
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMProfileSegmentChannelReach:
    segment = await _load_active_segment(context, segment_id)
    for permission in ("crm.communication_consent:view", "crm.contact_point:view"):
        await _require_permission(
            context, permission_key=permission,
            organization_unit_id=segment.organization_unit_id,
        )
    filters = await _segment_member_filters(context, segment)
    latest_decision = (
        select(CRMCommunicationConsentEvent.decision)
        .where(
            CRMCommunicationConsentEvent.tenant_id == context.access.tenant_id,
            CRMCommunicationConsentEvent.profile_id == CRMProfile.id,
            CRMCommunicationConsentEvent.purpose_key == purpose_key,
            CRMCommunicationConsentEvent.channel == channel,
        )
        .order_by(
            CRMCommunicationConsentEvent.recorded_at.desc(),
            CRMCommunicationConsentEvent.id.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    contact_exists = exists(select(1).where(
        CRMContactPoint.tenant_id == context.access.tenant_id,
        CRMContactPoint.profile_id == CRMProfile.id,
        CRMContactPoint.channel == channel,
        CRMContactPoint.verification_status != "invalid",
    ))
    verified_contact_exists = exists(select(1).where(
        CRMContactPoint.tenant_id == context.access.tenant_id,
        CRMContactPoint.profile_id == CRMProfile.id,
        CRMContactPoint.channel == channel,
        CRMContactPoint.verification_status == "verified",
    ))
    latest_granted = latest_decision == "granted"
    count_statement = select(func.count()).select_from(CRMProfile).where(*filters)
    total = int(await context.session.scalar(count_statement) or 0)
    with_contact = int(await context.session.scalar(count_statement.where(contact_exists)) or 0)
    verified = int(await context.session.scalar(count_statement.where(verified_contact_exists)) or 0)
    granted = int(await context.session.scalar(count_statement.where(latest_granted)) or 0)
    eligible = int(await context.session.scalar(
        count_statement.where(verified_contact_exists, latest_granted)
    ) or 0)
    withdrawn = int(await context.session.scalar(
        count_statement.where(latest_decision == "withdrawn")
    ) or 0)
    _audit(
        context,
        action_key="crm_profile_segment.channel_reach_reviewed",
        segment=segment,
        after_state={
            "purpose_key": purpose_key, "channel": channel,
            "total_profiles": total, "eligible_profiles": eligible,
        },
    )
    await context.session.flush()
    return CRMProfileSegmentChannelReach(
        segment_id=segment.id, purpose_key=purpose_key, channel=channel,
        total_profiles=total, profiles_with_contact=with_contact,
        profiles_with_verified_contact=verified, profiles_with_granted_consent=granted,
        eligible_profiles=eligible, withdrawn_consent_profiles=withdrawn,
        missing_or_withdrawn_consent_profiles=total - granted,
        eligibility_basis=(
            "Eligible profiles have a verified contact point on the selected channel and an explicit latest granted consent "
            "for the selected purpose. Missing consent is treated as not eligible."
        ),
    )


@router.get(
    "/{segment_id}/preview",
    response_model=CRMProfileSegmentPreview,
    operation_id="previewCRMProfileSegment",
    summary="Preview live audience membership in authorized profile scope",
)
async def preview_crm_profile_segment(
    segment_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CRMProfileSegmentPreview:
    segment = await _load_active_segment(context, segment_id)

    filters = await _segment_member_filters(context, segment)

    total = int(
        await context.session.scalar(
            select(func.count()).select_from(CRMProfile).where(*filters)
        )
        or 0
    )
    rows = (
        await context.session.execute(
            select(
                CRMProfile.id,
                CRMProfile.profile_kind,
                CRMProfile.display_name,
                CRMProfile.lifecycle_stage,
            )
            .where(*filters)
            .order_by(CRMProfile.display_name, CRMProfile.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    _audit(
        context,
        action_key="crm_profile_segment.previewed",
        segment=segment,
        after_state={"matched_profiles": total, "offset": offset, "limit": limit},
    )
    await context.session.flush()
    return CRMProfileSegmentPreview(
        segment_id=segment.id,
        total=total,
        items=[CRMProfileSegmentMember.model_validate(dict(row._mapping)) for row in rows],
        limit=limit,
        offset=offset,
    )
