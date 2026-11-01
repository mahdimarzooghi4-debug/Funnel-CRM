"""Manage campaign content assets and their approval lifecycle."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignAsset,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/marketing-assets", tags=["CRM marketing assets"])
AssetChannel = Literal["email", "phone", "messaging", "social", "web", "store", "field", "other"]
AssetKind = Literal["copy", "image", "video", "landing_page", "document", "other"]
AssetStatus = Literal["draft", "in_review", "approved", "rejected", "retired"]


class CampaignAssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    campaign_id: UUID | None = None
    channel: AssetChannel
    asset_kind: AssetKind
    title: str = Field(min_length=1, max_length=160)
    body: str | None = Field(default=None, max_length=12000)
    external_url: AnyHttpUrl | None = None
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must contain a non-whitespace character")
        return value

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_content_or_reference(self):
        if self.body is None and self.external_url is None:
            raise ValueError("provide body content, an external URL, or both")
        return self


class CampaignAssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: AssetChannel | None = None
    asset_kind: AssetKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, max_length=12000)
    external_url: AnyHttpUrl | None = None
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("title must contain a non-whitespace character")
        return value

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("at least one asset field must be supplied")
        return self


class CampaignAssetReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_rejection_note(self):
        if self.decision == "reject" and self.note is None:
            raise ValueError("a rejection note is required")
        return self


class CampaignAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    campaign_id: UUID | None
    channel: AssetChannel
    asset_kind: AssetKind
    title: str
    body: str | None
    external_url: str | None
    locale: str | None
    status: AssetStatus
    created_by_membership_id: UUID
    reviewed_by_membership_id: UUID | None
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


async def _require_permission(
    context: TenantSessionContext, permission_key: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Marketing asset action is not authorized for this organization scope")


async def _campaign_for_asset(
    context: TenantSessionContext, organization_unit_id: UUID, campaign_id: UUID | None
) -> CRMMarketingCampaign | None:
    if campaign_id is None:
        return None
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.organization_unit_id == organization_unit_id,
            CRMMarketingCampaign.id == campaign_id,
            CRMMarketingCampaign.status == "draft",
        )
    )
    if campaign is None:
        raise HTTPException(status_code=422, detail="Campaign must be an available draft in the selected organization")
    return campaign


def _audit(
    context: TenantSessionContext,
    asset: CRMMarketingCampaignAsset,
    action_key: str,
    before: dict | None,
    after: dict,
) -> None:
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key=action_key,
        target_type="crm_marketing_campaign_asset",
        target_key=str(asset.id),
        organization_unit_id=asset.organization_unit_id,
        before_state=before,
        after_state=after,
        correlation_id=None,
    ))


def _snapshot(asset: CRMMarketingCampaignAsset) -> dict:
    return {
        "organization_unit_id": str(asset.organization_unit_id),
        "campaign_id": str(asset.campaign_id) if asset.campaign_id else None,
        "channel": asset.channel,
        "asset_kind": asset.asset_kind,
        "title": asset.title,
        "status": asset.status,
        "reviewed_by_membership_id": str(asset.reviewed_by_membership_id) if asset.reviewed_by_membership_id else None,
    }


async def _load_asset(
    context: TenantSessionContext, asset_id: UUID
) -> CRMMarketingCampaignAsset:
    asset = await context.session.scalar(
        select(CRMMarketingCampaignAsset).where(
            CRMMarketingCampaignAsset.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignAsset.id == asset_id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Marketing asset not found")
    await _require_permission(context, "crm.campaign:view", asset.organization_unit_id)
    return asset


@router.post("", response_model=CampaignAssetRead, status_code=201,
             operation_id="createCRMMarketingCampaignAsset")
async def create_marketing_asset(
    payload: CampaignAssetCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignAssetRead:
    await _require_permission(context, "crm.campaign:manage", payload.organization_unit_id)
    campaign = await _campaign_for_asset(context, payload.organization_unit_id, payload.campaign_id)
    if campaign is not None and campaign.channel != payload.channel:
        raise HTTPException(status_code=422, detail="Asset channel must match its linked campaign")
    asset = CRMMarketingCampaignAsset(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        campaign_id=payload.campaign_id, channel=payload.channel,
        asset_kind=payload.asset_kind, title=payload.title, body=payload.body,
        external_url=str(payload.external_url) if payload.external_url else None,
        locale=payload.locale, status="draft",
        created_by_membership_id=context.access.membership_id,
        reviewed_by_membership_id=None, review_note=None, reviewed_at=None,
    )
    context.session.add(asset)
    await context.session.flush()
    _audit(context, asset, "crm_marketing_campaign_asset.created", None, _snapshot(asset))
    await context.session.flush()
    return CampaignAssetRead.model_validate(asset)


@router.get("", response_model=list[CampaignAssetRead],
            operation_id="listCRMMarketingCampaignAssets")
async def list_marketing_assets(
    organization_unit_id: UUID,
    campaign_id: UUID | None = None,
    status: AssetStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[CampaignAssetRead]:
    await _require_permission(context, "crm.campaign:view", organization_unit_id)
    statement = select(CRMMarketingCampaignAsset).where(
        CRMMarketingCampaignAsset.tenant_id == context.access.tenant_id,
        CRMMarketingCampaignAsset.organization_unit_id == organization_unit_id,
    )
    if campaign_id is not None:
        statement = statement.where(CRMMarketingCampaignAsset.campaign_id == campaign_id)
    if status is not None:
        statement = statement.where(CRMMarketingCampaignAsset.status == status)
    assets = (await context.session.scalars(
        statement.order_by(CRMMarketingCampaignAsset.updated_at.desc(), CRMMarketingCampaignAsset.id)
        .limit(limit).offset(offset)
    )).all()
    return [CampaignAssetRead.model_validate(asset) for asset in assets]


@router.patch("/{asset_id}", response_model=CampaignAssetRead,
              operation_id="updateCRMMarketingCampaignAsset")
async def update_marketing_asset(
    asset_id: UUID,
    payload: CampaignAssetUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignAssetRead:
    asset = await _load_asset(context, asset_id)
    await _require_permission(context, "crm.campaign:manage", asset.organization_unit_id)
    if asset.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="Only draft or rejected assets can be edited")
    before = _snapshot(asset)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "external_url" and value is not None:
            value = str(value)
        setattr(asset, key, value)
    if asset.body is None and asset.external_url is None:
        raise HTTPException(status_code=422, detail="Asset must retain body content or an external URL")
    campaign = await _campaign_for_asset(context, asset.organization_unit_id, asset.campaign_id)
    if campaign is not None and campaign.channel != asset.channel:
        raise HTTPException(status_code=422, detail="Asset channel must match its linked campaign")
    asset.status = "draft"
    asset.reviewed_by_membership_id = None
    asset.review_note = None
    asset.reviewed_at = None
    await context.session.flush()
    _audit(context, asset, "crm_marketing_campaign_asset.updated", before, _snapshot(asset))
    await context.session.flush()
    return CampaignAssetRead.model_validate(asset)


@router.post("/{asset_id}/submit", response_model=CampaignAssetRead,
             operation_id="submitCRMMarketingCampaignAsset")
async def submit_marketing_asset(
    asset_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignAssetRead:
    asset = await _load_asset(context, asset_id)
    await _require_permission(context, "crm.campaign:manage", asset.organization_unit_id)
    if asset.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="Only draft or rejected assets can be submitted for review")
    before = _snapshot(asset)
    asset.status = "in_review"
    asset.reviewed_by_membership_id = None
    asset.review_note = None
    asset.reviewed_at = None
    await context.session.flush()
    _audit(context, asset, "crm_marketing_campaign_asset.submitted", before, _snapshot(asset))
    await context.session.flush()
    return CampaignAssetRead.model_validate(asset)


@router.post("/{asset_id}/review", response_model=CampaignAssetRead,
             operation_id="reviewCRMMarketingCampaignAsset")
async def review_marketing_asset(
    asset_id: UUID,
    payload: CampaignAssetReview,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignAssetRead:
    asset = await _load_asset(context, asset_id)
    await _require_permission(context, "crm.campaign:manage", asset.organization_unit_id)
    if asset.status != "in_review":
        raise HTTPException(status_code=409, detail="Only assets in review can be approved or rejected")
    before = _snapshot(asset)
    asset.status = "approved" if payload.decision == "approve" else "rejected"
    asset.reviewed_by_membership_id = context.access.membership_id
    asset.review_note = payload.note
    asset.reviewed_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit(context, asset, "crm_marketing_campaign_asset.reviewed", before, _snapshot(asset) | {"decision": payload.decision, "review_note": payload.note})
    await context.session.flush()
    return CampaignAssetRead.model_validate(asset)
