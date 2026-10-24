"""Profile custom field values with definition-driven type validation."""

from datetime import date
import math
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import (
    CRMCustomFieldDefinition,
    CRMProfile,
    CRMProfileCustomFieldValue,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/profiles/{profile_id}/custom-fields",
    tags=["CRM profile custom fields"],
)


class CRMCustomFieldValueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any


class CRMCustomFieldValueRead(BaseModel):
    field_key: str
    display_name: str
    value_type: str
    options: list[str]
    is_required: bool
    value: Any | None


class CRMCustomFieldValuePage(BaseModel):
    items: list[CRMCustomFieldValueRead]


async def _get_authorized_profile(
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

    if not await has_crm_permission(
        context,
        permission_key="crm.profile:view",
        organization_unit_id=profile.organization_unit_id,
    ):
        raise HTTPException(status_code=404, detail="CRM profile not found")
    if not await has_crm_permission(
        context,
        permission_key=action_permission,
        organization_unit_id=profile.organization_unit_id,
    ):
        raise HTTPException(status_code=403, detail="CRM custom field action is not authorized")
    return profile


def _validated_value(definition: CRMCustomFieldDefinition, value: Any) -> Any:
    invalid = HTTPException(status_code=422, detail="Value does not match its custom field definition")
    if value is None or isinstance(value, (dict, list)):
        raise invalid

    if definition.value_type == "text":
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise invalid
        return value.strip()
    if definition.value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid
        if not math.isfinite(float(value)):
            raise invalid
        return value
    if definition.value_type == "boolean":
        if not isinstance(value, bool):
            raise invalid
        return value
    if definition.value_type == "date":
        if not isinstance(value, str):
            raise invalid
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise invalid from exc
        if parsed.isoformat() != value:
            raise invalid
        return value
    if definition.value_type == "choice":
        if not isinstance(value, str) or value not in definition.options:
            raise invalid
        return value
    raise HTTPException(status_code=422, detail="Unsupported custom field type")


def _read_value(
    definition: CRMCustomFieldDefinition,
    value: Any | None,
) -> CRMCustomFieldValueRead:
    return CRMCustomFieldValueRead(
        field_key=definition.field_key,
        display_name=definition.display_name,
        value_type=definition.value_type,
        options=definition.options,
        is_required=definition.is_required,
        value=value,
    )


@router.get(
    "",
    response_model=CRMCustomFieldValuePage,
    operation_id="listCRMProfileCustomFieldValues",
    summary="List active custom fields and values for a customer profile",
)
async def list_custom_field_values(
    profile_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMCustomFieldValuePage:
    profile = await _get_authorized_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.custom_field:view",
    )
    rows = (
        await context.session.execute(
            select(CRMCustomFieldDefinition, CRMProfileCustomFieldValue.value)
            .outerjoin(
                CRMProfileCustomFieldValue,
                (CRMProfileCustomFieldValue.tenant_id == CRMCustomFieldDefinition.tenant_id)
                & (CRMProfileCustomFieldValue.profile_id == profile.id)
                & (
                    CRMProfileCustomFieldValue.field_definition_id
                    == CRMCustomFieldDefinition.id
                ),
            )
            .where(
                CRMCustomFieldDefinition.tenant_id == context.access.tenant_id,
                CRMCustomFieldDefinition.entity_kind == profile.profile_kind,
                CRMCustomFieldDefinition.is_active.is_(True),
            )
            .order_by(CRMCustomFieldDefinition.field_key)
            .limit(200)
        )
    ).all()
    return CRMCustomFieldValuePage(
        items=[_read_value(definition, value) for definition, value in rows]
    )


@router.put(
    "/{field_key}",
    response_model=CRMCustomFieldValueRead,
    operation_id="setCRMProfileCustomFieldValue",
    summary="Validate and set one custom field value",
)
async def set_custom_field_value(
    profile_id: UUID,
    field_key: str,
    payload: CRMCustomFieldValueInput,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMCustomFieldValueRead:
    profile = await _get_authorized_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.custom_field:update",
    )
    definition = await context.session.scalar(
        select(CRMCustomFieldDefinition).where(
            CRMCustomFieldDefinition.tenant_id == context.access.tenant_id,
            CRMCustomFieldDefinition.entity_kind == profile.profile_kind,
            CRMCustomFieldDefinition.field_key == field_key,
            CRMCustomFieldDefinition.is_active.is_(True),
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Active custom field not found")

    value = _validated_value(definition, payload.value)
    stored = await context.session.scalar(
        select(CRMProfileCustomFieldValue).where(
            CRMProfileCustomFieldValue.tenant_id == context.access.tenant_id,
            CRMProfileCustomFieldValue.profile_id == profile.id,
            CRMProfileCustomFieldValue.field_definition_id == definition.id,
        )
    )
    if stored is None:
        stored = CRMProfileCustomFieldValue(
            id=uuid4(),
            tenant_id=context.access.tenant_id,
            profile_id=profile.id,
            field_definition_id=definition.id,
            value=value,
        )
        context.session.add(stored)
    else:
        stored.value = value
    await context.session.flush()
    return _read_value(definition, stored.value)
