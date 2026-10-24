"""Scoped duplicate suggestions from keyed contact-point fingerprints."""

from collections import defaultdict
from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, tuple_

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.contact_point_crypto import (
    ContactPointCryptoError,
    ContactPointKeyring,
)
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import CRMContactPoint, CRMProfile
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/profiles", tags=["CRM duplicate review"])


class DuplicateCandidateRead(BaseModel):
    profile_id: UUID
    display_name: str
    matching_channels: list[str]


class DuplicateCandidatePage(BaseModel):
    items: list[DuplicateCandidateRead]


@lru_cache(maxsize=1)
def _environment_keyring() -> ContactPointKeyring:
    return ContactPointKeyring.from_environment()


def _get_keyring(request: Request) -> ContactPointKeyring:
    configured = getattr(request.app.state, "contact_point_keyring", None)
    if isinstance(configured, ContactPointKeyring):
        return configured
    try:
        return _environment_keyring()
    except ContactPointCryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private duplicate matching is unavailable",
        ) from exc


@router.get(
    "/{profile_id}/possible-duplicates",
    response_model=DuplicateCandidatePage,
    operation_id="listCRMProfileDuplicateCandidates",
    summary="List in-scope profiles with exact contact matches",
)
async def list_duplicate_candidates(
    profile_id: UUID,
    request: Request,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> DuplicateCandidatePage:
    tenant_id = context.access.tenant_id
    profile = await context.session.scalar(
        select(CRMProfile).where(
            CRMProfile.tenant_id == tenant_id,
            CRMProfile.id == profile_id,
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="CRM profile not found")
    if profile.merged_into_profile_id is not None:
        raise HTTPException(status_code=409, detail="Merged profiles cannot start a duplicate review")
    if profile.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived profiles cannot start a duplicate review")

    for permission in ("crm.profile:view", "crm.profile:review_duplicates"):
        if not await has_crm_permission(
            context,
            permission_key=permission,
            organization_unit_id=profile.organization_unit_id,
        ):
            raise HTTPException(
                status_code=403,
                detail="CRM duplicate review is not authorized",
            )

    keyring = _get_keyring(request)
    source_points = (
        await context.session.scalars(
            select(CRMContactPoint).where(
                CRMContactPoint.tenant_id == tenant_id,
                CRMContactPoint.profile_id == profile.id,
                CRMContactPoint.match_fingerprint.is_not(None),
            )
        )
    ).all()
    if not source_points:
        return DuplicateCandidatePage(items=[])

    fingerprints: set[tuple[str, bytes]] = set()
    channels: set[str] = set()
    for point in source_points:
        channels.add(point.channel)
        try:
            value = keyring.decrypt(
                tenant_id=tenant_id,
                profile_id=profile.id,
                channel=point.channel,
                key_id=point.encryption_key_id,
                ciphertext=point.encrypted_value,
            )
            fingerprints.update(
                keyring.blind_indexes(
                    tenant_id=tenant_id,
                    channel=point.channel,
                    value=value,
                ).items()
            )
        except ContactPointCryptoError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Private duplicate matching is unavailable",
            ) from exc

    rows = (
        await context.session.execute(
            select(CRMProfile.id, CRMProfile.display_name, CRMContactPoint.channel)
            .join(
                CRMContactPoint,
                (CRMContactPoint.tenant_id == CRMProfile.tenant_id)
                & (CRMContactPoint.profile_id == CRMProfile.id),
            )
            .where(
                CRMProfile.tenant_id == tenant_id,
                CRMProfile.id != profile.id,
                CRMProfile.merged_into_profile_id.is_(None),
                CRMProfile.archived_at.is_(None),
                CRMProfile.organization_unit_id.in_(
                    crm_scope_ids(context, permission_key="crm.profile:view")
                ),
                CRMContactPoint.tenant_id == tenant_id,
                CRMContactPoint.channel.in_(sorted(channels)),
                tuple_(
                    CRMContactPoint.fingerprint_key_id,
                    CRMContactPoint.match_fingerprint,
                ).in_(sorted(fingerprints)),
            )
            .distinct()
            .order_by(CRMProfile.display_name, CRMProfile.id, CRMContactPoint.channel)
        )
    ).all()

    matches: dict[UUID, tuple[str, set[str]]] = {}
    for candidate_id, display_name, channel in rows:
        if candidate_id not in matches:
            matches[candidate_id] = (display_name, set())
        matches[candidate_id][1].add(channel)

    return DuplicateCandidatePage(
        items=[
            DuplicateCandidateRead(
                profile_id=candidate_id,
                display_name=display_name,
                matching_channels=sorted(matching_channels),
            )
            for candidate_id, (display_name, matching_channels) in matches.items()
        ]
    )
