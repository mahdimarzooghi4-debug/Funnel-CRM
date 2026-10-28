"""Manager review of campaign schedule, audience, content, and open follow-up."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import exists, func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_segments import _segment_member_filters
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMCommunicationConsentEvent,
    CRMContactPoint,
    CRMMarketingCampaignAsset,
    CRMProfile,
    CRMProfileSegment,
    CRMWorkItem,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/campaigns", tags=["CRM campaign readiness"])
AssetStatus = Literal["draft", "in_review", "approved", "rejected", "retired"]


class CampaignReadinessCheck(BaseModel):
    key: Literal["campaign_schedule", "active_audience", "approved_content", "channel_eligibility"]
    status: Literal["complete", "missing", "pending", "inactive", "not_authorized", "unsupported"]
    count: int | None
    explanation: str


class CampaignReadinessResponse(BaseModel):
    campaign_id: UUID
    campaign_name: str
    organization_unit_id: UUID
    channel: str
    starts_at: datetime | None
    ends_at: datetime | None
    launch_readiness: Literal["ready_for_manager_review", "needs_attention"]
    checks: list[CampaignReadinessCheck]
    asset_counts: dict[AssetStatus, int]
    open_work_item_count: int | None
    work_item_data_visible: bool
    generated_at: datetime
    basis: str


@router.get(
    "/{campaign_id}/readiness",
    response_model=CampaignReadinessResponse,
    operation_id="getCRMCampaignLaunchReadiness",
)
async def get_campaign_readiness(
    campaign_id: UUID,
    purpose_key: str = Query(default="marketing", pattern=r"^[a-z][a-z0-9_.-]{0,79}$"),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignReadinessResponse:
    campaign = await context.session.scalar(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not await has_crm_permission(
        context, permission_key="crm.campaign:view",
        organization_unit_id=campaign.organization_unit_id,
    ):
        raise HTTPException(status_code=403, detail="Campaign readiness is not authorized for this organization scope")
    if campaign.status != "draft":
        raise HTTPException(status_code=409, detail="Readiness review is available for draft campaigns")

    active_segment = await context.session.scalar(
        select(CRMProfileSegment).where(
            CRMProfileSegment.tenant_id == context.access.tenant_id,
            CRMProfileSegment.organization_unit_id == campaign.organization_unit_id,
            CRMProfileSegment.id == campaign.segment_id,
            CRMProfileSegment.is_active.is_(True),
        )
    )
    grouped_assets = (await context.session.execute(
        select(CRMMarketingCampaignAsset.status, func.count(CRMMarketingCampaignAsset.id))
        .where(
            CRMMarketingCampaignAsset.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignAsset.organization_unit_id == campaign.organization_unit_id,
            CRMMarketingCampaignAsset.campaign_id == campaign.id,
        )
        .group_by(CRMMarketingCampaignAsset.status)
    )).all()
    asset_counts: dict[AssetStatus, int] = {
        status: 0 for status in ("draft", "in_review", "approved", "rejected", "retired")
    }
    for status, count in grouped_assets:
        asset_counts[status] = int(count)
    approved_count = asset_counts["approved"]
    pending_count = asset_counts["draft"] + asset_counts["in_review"] + asset_counts["rejected"]
    content_status: Literal["complete", "missing", "pending"] = (
        "complete" if approved_count > 0 and pending_count == 0
        else "pending" if pending_count > 0
        else "missing"
    )
    schedule_ready = campaign.starts_at is not None and campaign.ends_at is not None
    audience_ready = active_segment is not None
    channel_map = {
        "email": "email",
        "phone": "phone",
        "messaging": "phone",
        "social": "social_handle",
        "web": "website",
        "store": "postal_address",
        "field": "postal_address",
    }
    communication_channel = channel_map.get(campaign.channel)
    eligibility_status: Literal["complete", "missing", "not_authorized", "unsupported"]
    eligible_count: int | None = None
    if communication_channel is None:
        eligibility_status = "unsupported"
        eligibility_explanation = "No communication-consent channel is mapped to this campaign channel."
    else:
        required_permissions = (
            "crm.profile:view",
            "crm.segment:view",
            "crm.contact_point:view",
            "crm.communication_consent:view",
        )
        permission_results = [
            await has_crm_permission(
                context,
                permission_key=permission,
                organization_unit_id=campaign.organization_unit_id,
            )
            for permission in required_permissions
        ]
        can_review_eligibility = all(permission_results)
        if not can_review_eligibility:
            eligibility_status = "not_authorized"
            eligibility_explanation = "The caller cannot review audience contact and consent eligibility."
        elif active_segment is None:
            eligibility_status = "missing"
            eligibility_explanation = "Link an active audience segment before reviewing channel eligibility."
        else:
            member_filters = await _segment_member_filters(context, active_segment)
            latest_decision = (
                select(CRMCommunicationConsentEvent.decision)
                .where(
                    CRMCommunicationConsentEvent.tenant_id == context.access.tenant_id,
                    CRMCommunicationConsentEvent.profile_id == CRMProfile.id,
                    CRMCommunicationConsentEvent.purpose_key == purpose_key,
                    CRMCommunicationConsentEvent.channel == communication_channel,
                )
                .order_by(
                    CRMCommunicationConsentEvent.recorded_at.desc(),
                    CRMCommunicationConsentEvent.id.desc(),
                )
                .limit(1)
                .scalar_subquery()
            )
            verified_contact = exists(select(1).where(
                CRMContactPoint.tenant_id == context.access.tenant_id,
                CRMContactPoint.profile_id == CRMProfile.id,
                CRMContactPoint.channel == communication_channel,
                CRMContactPoint.verification_status == "verified",
            ))
            eligible_count = int(await context.session.scalar(
                select(func.count()).select_from(CRMProfile).where(
                    *member_filters, verified_contact, latest_decision == "granted"
                )
            ) or 0)
            eligibility_status = "complete" if eligible_count > 0 else "missing"
            eligibility_explanation = (
                f"{eligible_count} profile(s) have a verified {communication_channel} contact "
                f"and current granted consent for purpose '{purpose_key}'."
                if eligible_count > 0
                else (
                    f"No profiles have both a verified {communication_channel} contact and "
                    f"current granted consent for purpose '{purpose_key}'."
                )
            )
    checks = [
        CampaignReadinessCheck(
            key="campaign_schedule",
            status="complete" if schedule_ready else "missing",
            count=2 if schedule_ready else int(campaign.starts_at is not None) + int(campaign.ends_at is not None),
            explanation="Both planned start and end times are set." if schedule_ready else "Set both planned start and end times.",
        ),
        CampaignReadinessCheck(
            key="active_audience",
            status="complete" if audience_ready else "inactive",
            count=1 if audience_ready else 0,
            explanation="The linked audience segment is active." if audience_ready else "Activate or replace the linked audience segment.",
        ),
        CampaignReadinessCheck(
            key="approved_content",
            status=content_status,
            count=approved_count,
            explanation=(
                "At least one campaign asset is approved and no assets are pending review."
                if content_status == "complete"
                else "Content is awaiting review or revision."
                if content_status == "pending"
                else "Approve at least one content asset for this campaign."
            ),
        ),
        CampaignReadinessCheck(
            key="channel_eligibility",
            status=eligibility_status,
            count=eligible_count,
            explanation=eligibility_explanation,
        ),
    ]
    work_item_scopes = set((await context.session.scalars(
        crm_scope_ids(context, permission_key="crm.work_item:view")
    )).all())
    work_item_data_visible = campaign.organization_unit_id in work_item_scopes
    open_work_item_count = None
    if work_item_data_visible:
        open_work_item_count = int(await context.session.scalar(
            select(func.count(CRMWorkItem.id)).where(
                CRMWorkItem.tenant_id == context.access.tenant_id,
                CRMWorkItem.organization_unit_id == campaign.organization_unit_id,
                CRMWorkItem.campaign_id == campaign.id,
                CRMWorkItem.status.in_(("open", "in_progress")),
            )
        ) or 0)
    return CampaignReadinessResponse(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        organization_unit_id=campaign.organization_unit_id,
        channel=campaign.channel,
        starts_at=campaign.starts_at,
        ends_at=campaign.ends_at,
        launch_readiness=(
            "ready_for_manager_review"
            if schedule_ready and audience_ready and content_status == "complete" and eligibility_status == "complete"
            else "needs_attention"
        ),
        checks=checks,
        asset_counts=asset_counts,
        open_work_item_count=open_work_item_count,
        work_item_data_visible=work_item_data_visible,
        generated_at=datetime.now(timezone.utc),
        basis=(
            "Readiness is a checklist for manager review, not an automatic launch approval. "
            "It requires a complete schedule, active audience, at least one approved asset with no unresolved content reviews, "
            "and at least one profile with a verified channel contact and latest granted consent for the requested purpose. "
            "Unsupported channels or missing access keep the review in needs_attention. "
            "Open work items are shown only when the caller has work-item view permission."
        ),
    )
