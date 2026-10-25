"""Tenant-scoped product and service catalog with immutable price history."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import AuditEvent, CRMProductCatalogItem, CRMProductCatalogPriceVersion
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/catalog/items", tags=["CRM product and service catalog"])


class CatalogItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_unit_id: UUID
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    item_type: str = Field(pattern=r"^(product|service)$")


class CatalogItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    item_type: str | None = Field(default=None, pattern=r"^(product|service)$")
    is_active: bool | None = None


class CatalogPriceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    effective_start: date | None = None
    effective_end: date | None = None


def _item_json(item: CRMProductCatalogItem) -> dict:
    return {
        "id": item.id, "organization_unit_id": item.organization_unit_id,
        "code": item.code, "name": item.name, "description": item.description,
        "item_type": item.item_type, "version": item.version,
        "is_active": item.is_active, "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _price_json(price: CRMProductCatalogPriceVersion) -> dict:
    return {
        "item_id": price.item_id, "version": price.version,
        "amount": price.amount, "currency": price.currency,
        "effective_start": price.effective_start, "effective_end": price.effective_end,
        "created_by_membership_id": price.created_by_membership_id,
        "created_at": price.created_at,
    }


async def _authorize(context: TenantSessionContext, action: str, organization_unit_id: UUID) -> None:
    if not await has_crm_permission(
        context, permission_key=action, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Catalog action is not authorized")


def _validate_window(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="Price effective start must not be after its end")


@router.post("", status_code=201, operation_id="createCRMProductCatalogItem")
async def create_catalog_item(
    payload: CatalogItemCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    await _authorize(context, "crm.catalog:manage", payload.organization_unit_id)
    code = payload.code.strip()
    name = payload.name.strip()
    if not code or not name:
        raise HTTPException(status_code=422, detail="Catalog code and name cannot be blank")
    duplicate = await context.session.scalar(select(CRMProductCatalogItem.id).where(
        CRMProductCatalogItem.tenant_id == context.access.tenant_id,
        CRMProductCatalogItem.organization_unit_id == payload.organization_unit_id,
        CRMProductCatalogItem.code == code,
    ))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Catalog code already exists in this organization unit")
    item = CRMProductCatalogItem(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id, code=code,
        name=name, description=payload.description.strip() if payload.description else None,
        item_type=payload.item_type, version=1, is_active=True,
        created_by_membership_id=context.access.membership_id,
    )
    context.session.add(item)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_catalog.item_created", target_type="crm_product_catalog_item",
        target_key=str(item.id), organization_unit_id=item.organization_unit_id,
        before_state=None, after_state={"code": code, "name": name, "item_type": item.item_type},
        correlation_id=None,
    ))
    await context.session.flush()
    return _item_json(item)


@router.get("", operation_id="listCRMProductCatalogItems")
async def list_catalog_items(
    organization_unit_id: UUID | None = None,
    item_type: str | None = Query(default=None, pattern=r"^(product|service)$"),
    active_only: bool = True,
    limit: int = Query(default=200, ge=1, le=500),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    scopes = crm_scope_ids(context, permission_key="crm.catalog:view")
    filters = [
        CRMProductCatalogItem.tenant_id == context.access.tenant_id,
        CRMProductCatalogItem.organization_unit_id.in_(scopes),
    ]
    if organization_unit_id is not None:
        await _authorize(context, "crm.catalog:view", organization_unit_id)
        filters.append(CRMProductCatalogItem.organization_unit_id == organization_unit_id)
    if item_type is not None:
        filters.append(CRMProductCatalogItem.item_type == item_type)
    if active_only:
        filters.append(CRMProductCatalogItem.is_active.is_(True))
    items = await context.session.scalars(select(CRMProductCatalogItem).where(*filters).order_by(
        CRMProductCatalogItem.name, CRMProductCatalogItem.id,
    ).limit(limit))
    return {"items": [_item_json(item) for item in items]}


@router.patch("/{item_id}", operation_id="updateCRMProductCatalogItem")
async def update_catalog_item(
    item_id: UUID,
    payload: CatalogItemUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    if not payload.model_fields_set - {"expected_version"}:
        raise HTTPException(status_code=422, detail="Provide at least one catalog item field")
    item = await context.session.scalar(select(CRMProductCatalogItem).where(
        CRMProductCatalogItem.tenant_id == context.access.tenant_id,
        CRMProductCatalogItem.id == item_id,
    ).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    await _authorize(context, "crm.catalog:manage", item.organization_unit_id)
    if payload.expected_version != item.version:
        raise HTTPException(status_code=409, detail="Catalog item version is stale")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    for field in payload.model_fields_set - {"expected_version"}:
        value = changes[field]
        if value is None and field != "description":
            raise HTTPException(status_code=422, detail=f"Catalog field {field} cannot be null")
        if field == "name":
            value = value.strip()
            if not value:
                raise HTTPException(status_code=422, detail="Catalog name cannot be blank")
        if field == "description" and value is not None:
            value = value.strip() or None
        changes[field] = value
    before = {key: getattr(item, key) for key in changes}
    for key, value in changes.items():
        setattr(item, key, value)
    item.version += 1
    item.updated_at = datetime.now(timezone.utc)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_catalog.item_updated", target_type="crm_product_catalog_item",
        target_key=str(item.id), organization_unit_id=item.organization_unit_id,
        before_state=before, after_state={**changes, "version": item.version}, correlation_id=None,
    ))
    await context.session.flush()
    return _item_json(item)


@router.post("/{item_id}/prices", status_code=201, operation_id="createCRMProductCatalogPriceVersion")
async def create_catalog_price(
    item_id: UUID,
    payload: CatalogPriceCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    item = await context.session.scalar(select(CRMProductCatalogItem).where(
        CRMProductCatalogItem.tenant_id == context.access.tenant_id,
        CRMProductCatalogItem.id == item_id,
    ).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    await _authorize(context, "crm.catalog:manage", item.organization_unit_id)
    if not item.is_active:
        raise HTTPException(status_code=409, detail="Inactive catalog items cannot receive new prices")
    _validate_window(payload.effective_start, payload.effective_end)
    latest = await context.session.scalar(select(func.max(CRMProductCatalogPriceVersion.version)).where(
        CRMProductCatalogPriceVersion.tenant_id == context.access.tenant_id,
        CRMProductCatalogPriceVersion.item_id == item.id,
    ))
    price = CRMProductCatalogPriceVersion(
        tenant_id=context.access.tenant_id, item_id=item.id, version=(latest or 0) + 1,
        amount=payload.amount, currency=payload.currency,
        effective_start=payload.effective_start, effective_end=payload.effective_end,
        created_by_membership_id=context.access.membership_id,
    )
    context.session.add(price)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_catalog.price_version_created", target_type="crm_product_catalog_item",
        target_key=str(item.id), organization_unit_id=item.organization_unit_id,
        before_state=None, after_state={"version": price.version, "amount": str(price.amount),
            "currency": price.currency, "effective_start": price.effective_start.isoformat() if price.effective_start else None,
            "effective_end": price.effective_end.isoformat() if price.effective_end else None},
        correlation_id=None,
    ))
    await context.session.flush()
    return _price_json(price)


@router.get("/{item_id}/prices", operation_id="listCRMProductCatalogPriceVersions")
async def list_catalog_prices(
    item_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> dict:
    item = await context.session.scalar(select(CRMProductCatalogItem).where(
        CRMProductCatalogItem.tenant_id == context.access.tenant_id,
        CRMProductCatalogItem.id == item_id,
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    await _authorize(context, "crm.catalog:view", item.organization_unit_id)
    prices = await context.session.scalars(select(CRMProductCatalogPriceVersion).where(
        CRMProductCatalogPriceVersion.tenant_id == context.access.tenant_id,
        CRMProductCatalogPriceVersion.item_id == item.id,
    ).order_by(CRMProductCatalogPriceVersion.version.desc()).limit(200))
    return {"items": [_price_json(price) for price in prices]}
