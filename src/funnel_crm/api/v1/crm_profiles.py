"""Tenant-scoped customer profile API with action and row-scope checks."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import CRMProfile, TenantRecord
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/profiles", tags=["CRM customer profiles"])


class CRMProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    profile_kind: str = Field(pattern=r"^(person|organization)$")
    display_name: str = Field(min_length=1, max_length=240)
    lifecycle_stage: str = Field(default="lead", min_length=1, max_length=80)

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
            return value
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
) -> CRMProfilePage:
    """Filter at the database query so out-of-scope rows never enter the result."""
    allowed_units = crm_scope_ids(context, permission_key="crm.profile:view")
    filters = [
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id.in_(allowed_units),
    ]
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
    return CRMProfileRead.model_validate(profile)


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

    for field_name, value in changes.items():
        setattr(profile, field_name, value)
    await context.session.flush()
