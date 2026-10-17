"""Protected contact-point APIs; plaintext is encrypted before database writes."""

from functools import lru_cache
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.contact_point_crypto import (
    ContactPointCryptoError,
    ContactPointKeyring,
)
from funnel_crm.platform.crm_authorization import has_crm_permission
from funnel_crm.platform.models import CRMContactPoint, CRMProfile
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(
    prefix="/crm/profiles/{profile_id}/contact-points",
    tags=["CRM customer contact points"],
)


class CRMContactPointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(
        pattern=r"^(email|phone|postal_address|social_handle|website)$"
    )
    value: str = Field(min_length=1, max_length=1000)
    is_primary: bool = False

    @staticmethod
    def _trim(value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must contain a non-whitespace character")
        return value

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict) and isinstance(obj.get("value"), str):
            obj = {**obj, "value": cls._trim(obj["value"])}
        return super().model_validate(obj, **kwargs)


class CRMContactPointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_primary: bool


class CRMContactPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: str
    value: str
    verification_status: str
    is_primary: bool


class CRMContactPointPage(BaseModel):
    items: list[CRMContactPointRead]


def _get_keyring(request: Request) -> ContactPointKeyring:
    configured = getattr(request.app.state, "contact_point_keyring", None)
    if isinstance(configured, ContactPointKeyring):
        return configured
    try:
        return _environment_keyring()
    except ContactPointCryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contact-point encryption is unavailable",
        ) from exc


@lru_cache(maxsize=1)
def _environment_keyring() -> ContactPointKeyring:
    return ContactPointKeyring.from_environment()


async def _get_profile(
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")

    if not await has_crm_permission(
        context,
        permission_key="crm.profile:view",
        organization_unit_id=profile.organization_unit_id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM profile not found")

    if not await has_crm_permission(
        context,
        permission_key=action_permission,
        organization_unit_id=profile.organization_unit_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CRM contact-point action is not authorized",
        )
    return profile


def _decrypt_contact_point(
    keyring: ContactPointKeyring,
    contact_point: CRMContactPoint,
) -> CRMContactPointRead:
    try:
        value = keyring.decrypt(
            tenant_id=contact_point.tenant_id,
            profile_id=contact_point.profile_id,
            channel=contact_point.channel,
            key_id=contact_point.encryption_key_id,
            ciphertext=contact_point.encrypted_value,
        )
    except ContactPointCryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contact-point data cannot be safely decrypted",
        ) from exc
    return CRMContactPointRead(
        id=contact_point.id,
        channel=contact_point.channel,
        value=value,
        verification_status=contact_point.verification_status,
        is_primary=contact_point.is_primary,
    )


@router.get(
    "",
    response_model=CRMContactPointPage,
    operation_id="listCRMContactPoints",
    summary="List encrypted contact points for an authorized customer",
)
async def list_contact_points(
    profile_id: UUID,
    request: Request,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMContactPointPage:
    profile = await _get_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.contact_point:view",
    )
    contact_points = (
        await context.session.scalars(
            select(CRMContactPoint)
            .where(
                CRMContactPoint.tenant_id == context.access.tenant_id,
                CRMContactPoint.profile_id == profile.id,
            )
            .order_by(CRMContactPoint.created_at, CRMContactPoint.id)
        )
    ).all()
    keyring = _get_keyring(request)
    return CRMContactPointPage(
        items=[_decrypt_contact_point(keyring, item) for item in contact_points]
    )


@router.post(
    "",
    response_model=CRMContactPointRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCRMContactPoint",
    summary="Encrypt and attach a customer contact point",
)
async def create_contact_point(
    profile_id: UUID,
    payload: CRMContactPointCreate,
    request: Request,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CRMContactPointRead:
    profile = await _get_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.contact_point:create",
    )
    keyring = _get_keyring(request)
    contact_point_id = uuid4()
    try:
        key_id, ciphertext = keyring.encrypt(
            tenant_id=context.access.tenant_id,
            profile_id=profile.id,
            channel=payload.channel,
            value=payload.value,
        )
    except ContactPointCryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contact-point encryption is unavailable",
        ) from exc

    if payload.is_primary:
        await context.session.execute(
            CRMContactPoint.__table__.update()
            .where(
                CRMContactPoint.tenant_id == context.access.tenant_id,
                CRMContactPoint.profile_id == profile.id,
                CRMContactPoint.channel == payload.channel,
                CRMContactPoint.is_primary.is_(True),
            )
            .values(is_primary=False)
        )

    contact_point = CRMContactPoint(
        id=contact_point_id,
        tenant_id=context.access.tenant_id,
        profile_id=profile.id,
        channel=payload.channel,
        encrypted_value=ciphertext,
        encryption_key_id=key_id,
        verification_status="unverified",
        is_primary=payload.is_primary,
    )
    context.session.add(contact_point)
    await context.session.flush()
    return _decrypt_contact_point(keyring, contact_point)


@router.patch(
    "/{contact_point_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="updateCRMContactPointMetadata",
    summary="Change the primary contact point for a channel",
)
async def update_contact_point(
    profile_id: UUID,
    contact_point_id: UUID,
    payload: CRMContactPointUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> None:
    profile = await _get_profile(
        context,
        profile_id=profile_id,
        action_permission="crm.contact_point:update",
    )
    contact_point = await context.session.scalar(
        select(CRMContactPoint).where(
            CRMContactPoint.tenant_id == context.access.tenant_id,
            CRMContactPoint.profile_id == profile.id,
            CRMContactPoint.id == contact_point_id,
        )
    )
    if contact_point is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CRM contact point not found",
        )

    if payload.is_primary:
        await context.session.execute(
            CRMContactPoint.__table__.update()
            .where(
                CRMContactPoint.tenant_id == context.access.tenant_id,
                CRMContactPoint.profile_id == profile.id,
                CRMContactPoint.channel == contact_point.channel,
                CRMContactPoint.id != contact_point.id,
                CRMContactPoint.is_primary.is_(True),
            )
            .values(is_primary=False)
        )
    contact_point.is_primary = payload.is_primary
    await context.session.flush()
