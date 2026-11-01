"""Scoped registry for organizations and people operating sales channels."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import AuditEvent, CRMChannelPartner, OrganizationUnit
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/channel-partners", tags=["CRM channel partners"])
PARTNER_TYPES = {"reseller", "affiliate", "agency", "distributor", "referral", "other"}
PARTNER_STATUSES = {"prospect", "active", "paused", "ended"}


class PartnerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_unit_id: UUID
    name: str = Field(min_length=1, max_length=180)
    partner_type: str
    status: str = "prospect"
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    territory: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)


class PartnerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    partner_type: str | None = None
    status: str | None = None
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    territory: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)


def _json(row: CRMChannelPartner) -> dict:
    return {key: getattr(row, key) for key in ("id", "organization_unit_id", "name", "partner_type", "status", "contact_name", "email", "phone", "territory", "notes", "version", "created_at", "updated_at")}


def _audit(context: TenantSessionContext, action: str, row: CRMChannelPartner, before: dict | None = None) -> None:
    safe_state = {"name": row.name, "partner_type": row.partner_type, "status": row.status, "territory": row.territory, "version": row.version}
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key=action, target_type="crm_channel_partner", target_key=str(row.id),
        organization_unit_id=row.organization_unit_id, before_state=before,
        after_state=safe_state, correlation_id=None,
    ))


async def _authorize(context: TenantSessionContext, action: str, unit_id: UUID) -> None:
    if not await has_crm_permission(context, permission_key=action, organization_unit_id=unit_id):
        raise HTTPException(status_code=403, detail="Channel partner action is not authorized")


def _validate(payload: BaseModel) -> None:
    values = payload.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None and not values["name"].strip():
        raise HTTPException(status_code=422, detail="Partner name cannot be blank")
    if values.get("partner_type") is not None and values["partner_type"] not in PARTNER_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported partner type")
    if values.get("status") is not None and values["status"] not in PARTNER_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported partner status")


@router.get("")
async def list_partners(
    organization_unit_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=180),
    partner_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if partner_type is not None and partner_type not in PARTNER_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported partner type")
    if status is not None and status not in PARTNER_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported partner status")
    scope = crm_scope_ids(context, permission_key="crm.partner:view")
    query = select(CRMChannelPartner).where(CRMChannelPartner.tenant_id == context.access.tenant_id, CRMChannelPartner.organization_unit_id.in_(scope))
    if organization_unit_id:
        query = query.where(CRMChannelPartner.organization_unit_id == organization_unit_id)
    if search and search.strip():
        query = query.where(CRMChannelPartner.name.icontains(search.strip(), autoescape=True))
    if partner_type is not None:
        query = query.where(CRMChannelPartner.partner_type == partner_type)
    if status is not None:
        query = query.where(CRMChannelPartner.status == status)
    total = await context.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await context.session.scalars(query.order_by(CRMChannelPartner.name, CRMChannelPartner.id).limit(limit).offset(offset))
    return {"items": [_json(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201)
async def create_partner(payload: PartnerCreate, context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    await _authorize(context, "crm.partner:manage", payload.organization_unit_id)
    _validate(payload)
    if not await context.session.scalar(select(OrganizationUnit.id).where(OrganizationUnit.tenant_id == context.access.tenant_id, OrganizationUnit.id == payload.organization_unit_id)):
        raise HTTPException(status_code=404, detail="Organization unit not found")
    row = CRMChannelPartner(id=uuid4(), tenant_id=context.access.tenant_id, created_by_membership_id=context.access.membership_id, **{**payload.model_dump(), "name": payload.name.strip()})
    context.session.add(row)
    _audit(context, "crm_channel_partner.created", row)
    await context.session.flush()
    return _json(row)


@router.get("/{partner_id}")
async def get_partner(partner_id: UUID, context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    row = await context.session.scalar(select(CRMChannelPartner).where(
        CRMChannelPartner.tenant_id == context.access.tenant_id,
        CRMChannelPartner.id == partner_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Channel partner not found")
    await _authorize(context, "crm.partner:view", row.organization_unit_id)
    return _json(row)


@router.patch("/{partner_id}")
async def update_partner(partner_id: UUID, payload: PartnerUpdate, context: TenantSessionContext = Depends(require_tenant_session)) -> dict:
    # Serialize writers before checking the expected version. Without this lock,
    # two transactions can both accept version N and overwrite one another.
    row = await context.session.scalar(
        select(CRMChannelPartner).where(
            CRMChannelPartner.tenant_id == context.access.tenant_id,
            CRMChannelPartner.id == partner_id,
        ).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Channel partner not found")
    await _authorize(context, "crm.partner:manage", row.organization_unit_id)
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Channel partner changed; reload before updating")
    _validate(payload)
    before = {"name": row.name, "partner_type": row.partner_type, "status": row.status, "territory": row.territory, "version": row.version}
    for key, value in payload.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        if value is not None or key in {"contact_name", "email", "phone", "territory", "notes"}:
            setattr(row, key, value.strip() if key == "name" and isinstance(value, str) else value)
    row.version += 1
    row.updated_at = datetime.now(timezone.utc)
    _audit(context, "crm_channel_partner.updated", row, before)
    await context.session.flush()
    return _json(row)
