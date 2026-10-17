"""Tenant-scoped customer profile API with action and row-scope checks."""

import csv
import io
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_custom_field_values import _validated_value
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomFieldDefinition,
    CRMProfile,
    CRMProfileCustomFieldValue,
    TenantRecord,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/profiles", tags=["CRM customer profiles"])


class CRMProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    profile_kind: str = Field(pattern=r"^(person|organization)$")
    display_name: str = Field(min_length=1, max_length=240)
    lifecycle_stage: str = Field(default="lead", min_length=1, max_length=80)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("display_name", "lifecycle_stage")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value


class CRMProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=240)
    lifecycle_stage: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("display_name", "lifecycle_stage")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("explicit null is not allowed")
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value


class CRMProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    profile_kind: str
    display_name: str
    lifecycle_stage: str
    merged_into_profile_id: UUID | None
    archived_at: datetime | None


class CRMProfilePage(BaseModel):
    items: list[CRMProfileRead]
    total: int
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
            detail="CRM action is not authorized for this organization scope",
        )


@router.get(
    "",
    response_model=CRMProfilePage,
    operation_id="listCRMProfiles",
    summary="List customer profiles in the caller's authorized scope",
)
async def list_crm_profiles(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_archived: bool = Query(default=False),
) -> CRMProfilePage:
    """Filter at the database query so out-of-scope rows never enter the result."""
    allowed_units = crm_scope_ids(context, permission_key="crm.profile:view")
    filters = [
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id.in_(allowed_units),
        CRMProfile.merged_into_profile_id.is_(None),
    ]
    if include_archived:
        archive_units = crm_scope_ids(context, permission_key="crm.profile:archive", cte_name="crm_archive_scope")
        filters.extend([
            CRMProfile.archived_at.is_not(None),
            CRMProfile.organization_unit_id.in_(archive_units),
        ])
    else:
        filters.append(CRMProfile.archived_at.is_(None))
    if organization_unit_id is not None:
        filters.append(CRMProfile.organization_unit_id == organization_unit_id)

    total = await context.session.scalar(
        select(func.count()).select_from(CRMProfile).where(*filters)
    )
    profiles = (
        await context.session.scalars(
            select(CRMProfile)
            .where(*filters)
            .order_by(CRMProfile.created_at.desc(), CRMProfile.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return CRMProfilePage(
        items=[CRMProfileRead.model_validate(profile) for profile in profiles],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )



@router.get(
    "/export.csv",
    response_class=Response,
    operation_id="exportCRMProfilesCsv",
    summary="Export in-scope customer profiles as CSV",
)
async def export_crm_profiles_csv(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
) -> Response:
    view_scope = crm_scope_ids(
        context,
        permission_key="crm.profile:view",
        cte_name="crm_export_view_scope",
    )
    export_scope = crm_scope_ids(
        context,
        permission_key="crm.profile:export",
        cte_name="crm_export_permission_scope",
    )
    filters = [
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id.in_(view_scope),
        CRMProfile.organization_unit_id.in_(export_scope),
        CRMProfile.merged_into_profile_id.is_(None),
        CRMProfile.archived_at.is_(None),
    ]
    if organization_unit_id is not None:
        filters.append(CRMProfile.organization_unit_id == organization_unit_id)

    total = int(
        await context.session.scalar(
            select(func.count()).select_from(CRMProfile).where(*filters)
        )
        or 0
    )
    if total > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Export exceeds the requested row limit; increase limit or use offset batches",
        )

    rows = (
        await context.session.execute(
            select(
                CRMProfile.id,
                CRMProfile.organization_unit_id,
                CRMProfile.profile_kind,
                CRMProfile.display_name,
                CRMProfile.lifecycle_stage,
                CRMProfile.created_at,
                CRMProfile.updated_at,
            )
            .where(*filters)
            .order_by(CRMProfile.created_at, CRMProfile.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    def csv_cell(value: object) -> str:
        text_value = value.isoformat() if isinstance(value, datetime) else str(value)
        if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + text_value
        return text_value

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "profile_id",
            "organization_unit_id",
            "profile_kind",
            "display_name",
            "lifecycle_stage",
            "created_at",
            "updated_at",
        ]
    )
    for row in rows:
        writer.writerow([csv_cell(value) for value in row])

    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="crm_profile.exported",
            target_type="crm_profile_export",
            target_key="csv",
            organization_unit_id=organization_unit_id,
            before_state=None,
            after_state={
                "format": "csv",
                "rows": len(rows),
                "offset": offset,
                "limit": limit,
            },
            correlation_id=None,
        )
    )
    await context.session.flush()
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="crm-profiles.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "",
    response_model=CRMProfileRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCRMProfile",
    summary="Create a person or organization customer profile",
)
async def create_crm_profile(
    payload: CRMProfileCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMProfileRead:
    await _require_permission(
        context,
        permission_key="crm.profile:create",
        organization_unit_id=payload.organization_unit_id,
    )

    definitions = (
        await context.session.scalars(
            select(CRMCustomFieldDefinition).where(
                CRMCustomFieldDefinition.tenant_id == context.access.tenant_id,
                CRMCustomFieldDefinition.entity_kind == payload.profile_kind,
                CRMCustomFieldDefinition.is_active.is_(True),
            )
        )
    ).all()
    definitions_by_key = {definition.field_key: definition for definition in definitions}
    unknown = set(payload.custom_fields) - definitions_by_key.keys()
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={"message": "Unknown custom field key", "field_keys": sorted(unknown)},
        )
    missing = sorted(
        definition.field_key
        for definition in definitions
        if definition.is_required and definition.field_key not in payload.custom_fields
    )
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "Required custom fields are missing", "field_keys": missing},
        )

    validated_values: list[tuple[CRMCustomFieldDefinition, Any]] = []
    for field_key, raw_value in payload.custom_fields.items():
        definition = definitions_by_key[field_key]
        validated_values.append((definition, _validated_value(definition, raw_value)))

    profile_id = uuid4()
    context.session.add(
        TenantRecord(
            id=profile_id,
            tenant_id=context.access.tenant_id,
            organization_unit_id=payload.organization_unit_id,
            record_type="crm_profile",
        )
    )
    await context.session.flush()
    profile = CRMProfile(
        id=profile_id,
        tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        profile_kind=payload.profile_kind,
        display_name=payload.display_name,
        lifecycle_stage=payload.lifecycle_stage,
    )
    context.session.add(profile)
    await context.session.flush()
    context.session.add_all(
        CRMProfileCustomFieldValue(
            id=uuid4(),
            tenant_id=context.access.tenant_id,
            profile_id=profile_id,
            field_definition_id=definition.id,
            value=value,
        )
        for definition, value in validated_values
    )
    await context.session.flush()
    return CRMProfileRead.model_validate(profile)


@router.post(
    "/{profile_id}/merge-into/{target_id}",
    response_model=CRMProfileRead,
    operation_id="mergeCRMProfileIntoSurvivor",
    summary="Mark a duplicate profile as merged into a surviving profile",
)
async def merge_crm_profile(
    profile_id: UUID,
    target_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMProfileRead:
    if profile_id == target_id:
        raise HTTPException(status_code=422, detail="A profile cannot be merged into itself")
    profiles = (
        await context.session.scalars(
            select(CRMProfile)
            .where(
                CRMProfile.tenant_id == context.access.tenant_id,
                CRMProfile.id.in_([profile_id, target_id]),
            )
            .order_by(CRMProfile.id)
            .with_for_update()
        )
    ).all()
    by_id = {profile.id: profile for profile in profiles}
    source = by_id.get(profile_id)
    target = by_id.get(target_id)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="CRM profile not found")

    for profile in (source, target):
        for permission in ("crm.profile:view", "crm.profile:update", "crm.profile:review_duplicates"):
            if not await has_crm_permission(
                context,
                permission_key=permission,
                organization_unit_id=profile.organization_unit_id,
            ):
                raise HTTPException(status_code=403, detail="CRM profile merge is not authorized")

    if source.archived_at is not None or target.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived profiles cannot be merged")
    if source.profile_kind != target.profile_kind:
        raise HTTPException(status_code=409, detail="Only profiles of the same kind can be merged")
    if source.merged_into_profile_id is not None:
        if source.merged_into_profile_id == target.id:
            return CRMProfileRead.model_validate(source)
        raise HTTPException(status_code=409, detail="Source profile is already merged")
    if target.merged_into_profile_id is not None:
        raise HTTPException(status_code=409, detail="Target profile is already merged")

    source.merged_into_profile_id = target.id
    await context.session.flush()
    return CRMProfileRead.model_validate(source)



@router.post(
    "/{profile_id}/archive",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="archiveCRMProfile",
    summary="Archive a customer profile while preserving its history",
)
async def archive_crm_profile(
    profile_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    profile = await context.session.scalar(
        select(CRMProfile)
        .where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.id == profile_id,
        )
        .with_for_update()
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")
    await _require_permission(
        context,
        permission_key="crm.profile:archive",
        organization_unit_id=profile.organization_unit_id,
    )
    if profile.merged_into_profile_id is not None:
        raise HTTPException(status_code=409, detail="Merged profiles cannot be archived")
    if profile.archived_at is None:
        profile.archived_at = datetime.now(timezone.utc)
        await context.session.flush()


@router.post(
    "/{profile_id}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="restoreCRMProfile",
    summary="Restore an archived customer profile",
)
async def restore_crm_profile(
    profile_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    profile = await context.session.scalar(
        select(CRMProfile)
        .where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.id == profile_id,
        )
        .with_for_update()
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")
    await _require_permission(
        context,
        permission_key="crm.profile:archive",
        organization_unit_id=profile.organization_unit_id,
    )
    if profile.merged_into_profile_id is not None:
        raise HTTPException(status_code=409, detail="Merged profiles cannot be restored")
    if profile.archived_at is not None:
        profile.archived_at = None
        await context.session.flush()

@router.get(
    "/{profile_id}",
    response_model=CRMProfileRead,
    operation_id="getCRMProfile",
    summary="Get a customer profile within the caller's scope",
)
async def get_crm_profile(
    profile_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMProfileRead:
    profile = await context.session.scalar(
        select(CRMProfile).where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.id == profile_id,
            CRMProfile.organization_unit_id.in_(
                crm_scope_ids(context, permission_key="crm.profile:view")
            ),
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")
    if profile.merged_into_profile_id is not None:
        target_org_id = await context.session.scalar(
            select(CRMProfile.organization_unit_id).where(
                CRMProfile.tenant_id == context.access.tenant_id,
                CRMProfile.id == profile.merged_into_profile_id,
            )
        )
        if target_org_id is None or not await has_crm_permission(
            context,
            permission_key="crm.profile:view",
            organization_unit_id=target_org_id,
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")
    return CRMProfileRead.model_validate(profile)


@router.patch(
    "/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="updateCRMProfile",
    summary="Update an in-scope customer profile",
)
async def update_crm_profile(
    profile_id: UUID,
    payload: CRMProfileUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one field is required")

    profile = await context.session.scalar(
        select(CRMProfile).where(
            CRMProfile.tenant_id == context.access.tenant_id,
            CRMProfile.id == profile_id,
            CRMProfile.organization_unit_id.in_(
                crm_scope_ids(context, permission_key="crm.profile:update")
            ),
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")
    if profile.archived_at is not None or profile.merged_into_profile_id is not None:
        raise HTTPException(status_code=409, detail="Archived or merged profiles are read-only")

    for field_name, value in changes.items():
        setattr(profile, field_name, value)
    await context.session.flush()
