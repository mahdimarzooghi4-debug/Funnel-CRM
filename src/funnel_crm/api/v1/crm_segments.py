"""Tenant- and organization-scoped saved customer audience segments."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMProfile,
    CRMProfileSegment,
    OrganizationUnit,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/segments", tags=["CRM audience segments"])


class CRMProfileSegmentCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_kinds: list[Literal["person", "organization"]] | None = Field(default=None, max_length=2)
    lifecycle_stages: list[str] | None = Field(default=None, max_length=20)

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
        if self.profile_kinds is None and self.lifecycle_stages is None:
            raise ValueError("At least one profile filter is required")
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
    if "name" in changes:
        segment.name = changes["name"]
    if "criteria" in changes:
        criteria = changes["criteria"]
        if criteria is None:
            raise HTTPException(status_code=422, detail="criteria cannot be null")
        segment.criteria = criteria.model_dump(exclude_none=True)
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
        context,
        permission_key="crm.profile:view",
        organization_unit_id=segment.organization_unit_id,
    )

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
    filters = [
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id.in_(segment_units),
        CRMProfile.organization_unit_id.in_(
            crm_scope_ids(
                context,
                permission_key="crm.profile:view",
                cte_name="crm_segment_profile_scope",
            )
        ),
        CRMProfile.merged_into_profile_id.is_(None),
        CRMProfile.archived_at.is_(None),
    ]
    if criteria.profile_kinds is not None:
        filters.append(CRMProfile.profile_kind.in_(criteria.profile_kinds))
    if criteria.lifecycle_stages is not None:
        filters.append(CRMProfile.lifecycle_stage.in_(criteria.lifecycle_stages))

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
