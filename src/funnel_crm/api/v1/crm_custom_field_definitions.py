"""Workspace-level management for CRM custom field definitions."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_custom_field_values import _validated_value
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    CRMCustomFieldDefinition,
    CRMProfile,
    CRMProfileCustomFieldValue,
    Workspace,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/custom-fields", tags=["CRM custom field definitions"])
ENTITY_KINDS = {"person", "organization", "lead", "opportunity"}
VALUE_TYPES = {"text", "number", "boolean", "date", "choice"}


class CRMCustomFieldDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_kind: str
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    display_name: str = Field(min_length=1, max_length=160)
    value_type: str
    options: list[str] = Field(default_factory=list, max_length=100)
    is_required: bool = False

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value

    @field_validator("options")
    @classmethod
    def clean_options(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 160 for item in cleaned):
            raise ValueError("options must be nonempty strings of at most 160 characters")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("options must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_definition(self):
        if self.entity_kind not in ENTITY_KINDS:
            raise ValueError("unsupported entity kind")
        if self.value_type not in VALUE_TYPES:
            raise ValueError("unsupported custom field type")
        if (self.value_type == "choice") != bool(self.options):
            raise ValueError("choice fields require options; other types must not have them")
        return self


class CRMCustomFieldDefinitionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    options: list[str] | None = Field(default=None, max_length=100)
    is_required: bool | None = None
    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("explicit null is not allowed")
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value

    @field_validator("options")
    @classmethod
    def clean_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            raise ValueError("explicit null is not allowed")
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 160 for item in cleaned):
            raise ValueError("options must be nonempty strings of at most 160 characters")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("options must be unique")
        return cleaned

    @field_validator("is_required", "is_active")
    @classmethod
    def reject_null_flags(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("explicit null is not allowed")
        return value


class CRMCustomFieldDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_kind: str
    field_key: str
    display_name: str
    value_type: str
    options: list[str]
    is_required: bool
    is_active: bool


async def _require_manager(context: TenantSessionContext) -> None:
    workspace = await context.session.get(Workspace, context.access.tenant_id)
    if workspace is None or not await has_crm_permission(
        context,
        permission_key="crm.custom_field:manage",
        organization_unit_id=workspace.root_organization_id,
    ):
        raise HTTPException(status_code=403, detail="CRM custom field management is not authorized")


@router.get("", response_model=list[CRMCustomFieldDefinitionRead], operation_id="listCRMCustomFieldDefinitions")
async def list_custom_field_definitions(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[CRMCustomFieldDefinitionRead]:
    await _require_manager(context)
    rows = (
        await context.session.scalars(
            select(CRMCustomFieldDefinition)
            .where(CRMCustomFieldDefinition.tenant_id == context.access.tenant_id)
            .order_by(CRMCustomFieldDefinition.entity_kind, CRMCustomFieldDefinition.field_key)
            .limit(500)
        )
    ).all()
    return [CRMCustomFieldDefinitionRead.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=CRMCustomFieldDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCRMCustomFieldDefinition",
)
async def create_custom_field_definition(
    payload: CRMCustomFieldDefinitionCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMCustomFieldDefinitionRead:
    await _require_manager(context)
    if payload.is_required:
        existing = await context.session.scalar(
            select(func.count()).select_from(CRMProfile).where(
                CRMProfile.tenant_id == context.access.tenant_id,
                CRMProfile.profile_kind == payload.entity_kind,
            )
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Create required fields before profiles of this kind exist",
            )
    definition = CRMCustomFieldDefinition(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        entity_kind=payload.entity_kind,
        field_key=payload.field_key,
        display_name=payload.display_name,
        value_type=payload.value_type,
        options=payload.options,
        is_required=payload.is_required,
        is_active=True,
    )
    context.session.add(definition)
    await context.session.flush()
    return CRMCustomFieldDefinitionRead.model_validate(definition)


@router.patch(
    "/{field_key}",
    response_model=CRMCustomFieldDefinitionRead,
    operation_id="updateCRMCustomFieldDefinition",
)
async def update_custom_field_definition(
    field_key: str,
    payload: CRMCustomFieldDefinitionUpdate,
    entity_kind: str,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMCustomFieldDefinitionRead:
    await _require_manager(context)
    if entity_kind not in ENTITY_KINDS:
        raise HTTPException(status_code=422, detail="Unsupported entity kind")
    definition = await context.session.scalar(
        select(CRMCustomFieldDefinition).where(
            CRMCustomFieldDefinition.tenant_id == context.access.tenant_id,
            CRMCustomFieldDefinition.entity_kind == entity_kind,
            CRMCustomFieldDefinition.field_key == field_key,
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Custom field definition not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field is required")

    new_options = changes.get("options", definition.options)
    if definition.value_type == "choice" and not new_options:
        raise HTTPException(status_code=422, detail="Choice fields must retain at least one option")
    if definition.value_type != "choice" and "options" in changes:
        raise HTTPException(status_code=422, detail="Only choice fields can have options")

    if "options" in changes and definition.value_type == "choice":
        values = (
            await context.session.scalars(
                select(CRMProfileCustomFieldValue.value).where(
                    CRMProfileCustomFieldValue.tenant_id == context.access.tenant_id,
                    CRMProfileCustomFieldValue.field_definition_id == definition.id,
                )
            )
        ).all()
        candidate = CRMCustomFieldDefinition(
            tenant_id=definition.tenant_id,
            entity_kind=definition.entity_kind,
            field_key=definition.field_key,
            display_name=definition.display_name,
            value_type=definition.value_type,
            options=new_options,
        )
        for value in values:
            try:
                _validated_value(candidate, value)
            except HTTPException as exc:
                raise HTTPException(
                    status_code=409,
                    detail="Options cannot invalidate values already stored on profiles",
                ) from exc

    if changes.get("is_required") is True and not definition.is_required:
        missing = await context.session.scalar(
            select(func.count())
            .select_from(CRMProfile)
            .outerjoin(
                CRMProfileCustomFieldValue,
                (CRMProfileCustomFieldValue.tenant_id == CRMProfile.tenant_id)
                & (CRMProfileCustomFieldValue.profile_id == CRMProfile.id)
                & (CRMProfileCustomFieldValue.field_definition_id == definition.id),
            )
            .where(
                CRMProfile.tenant_id == context.access.tenant_id,
                CRMProfile.profile_kind == definition.entity_kind,
                CRMProfileCustomFieldValue.id.is_(None),
            )
        )
        if missing:
            raise HTTPException(
                status_code=409,
                detail="Every existing profile must have a value before this field becomes required",
            )

    for name, value in changes.items():
        setattr(definition, name, value)
    await context.session.flush()
    return CRMCustomFieldDefinitionRead.model_validate(definition)


@router.delete(
    "/{field_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deactivateCRMCustomFieldDefinition",
)
async def deactivate_custom_field_definition(
    field_key: str,
    entity_kind: str,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    await _require_manager(context)
    definition = await context.session.scalar(
        select(CRMCustomFieldDefinition).where(
            CRMCustomFieldDefinition.tenant_id == context.access.tenant_id,
            CRMCustomFieldDefinition.entity_kind == entity_kind,
            CRMCustomFieldDefinition.field_key == field_key,
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Custom field definition not found")
    if definition.is_active:
        definition.is_active = False
        await context.session.flush()
