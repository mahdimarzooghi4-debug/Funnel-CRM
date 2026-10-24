"""Organization-scoped customer support cases and response work queue."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import case, func, select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCustomerSupportCase,
    CRMProfile,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/support-cases", tags=["CRM customer support"])
SupportCaseStatus = Literal["open", "in_progress", "waiting_customer", "resolved", "closed"]
SupportCasePriority = Literal["low", "normal", "high", "urgent"]


class SupportCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    profile_id: UUID
    assigned_membership_id: UUID | None = None
    subject: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    priority: SupportCasePriority = "normal"
    response_due_at: datetime | None = None

    @field_validator("subject")
    @classmethod
    def clean_subject(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("subject must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("response_due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("response_due_at must include a timezone")
        return value


class SupportCaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_membership_id: UUID | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: SupportCaseStatus | None = None
    priority: SupportCasePriority | None = None
    response_due_at: datetime | None = None

    @field_validator("subject")
    @classmethod
    def clean_subject(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("subject must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("response_due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("response_due_at must include a timezone")
        return value

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for key in ("subject", "status", "priority"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class SupportCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    profile_id: UUID
    assigned_membership_id: UUID | None
    created_by_membership_id: UUID
    subject: str
    description: str | None
    status: SupportCaseStatus
    priority: SupportCasePriority
    response_due_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SupportCasePage(BaseModel):
    items: list[SupportCaseRead]
    total: int
    overdue_count: int
    limit: int
    offset: int


async def _require(
    context: TenantSessionContext, permission_key: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission_key, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="CRM support case action is not authorized")


async def _validate_profile(
    context: TenantSessionContext, organization_unit_id: UUID, profile_id: UUID
) -> None:
    profile = await context.session.scalar(select(CRMProfile.id).where(
        CRMProfile.tenant_id == context.access.tenant_id,
        CRMProfile.organization_unit_id == organization_unit_id,
        CRMProfile.id == profile_id,
        CRMProfile.archived_at.is_(None),
        CRMProfile.merged_into_profile_id.is_(None),
    ))
    if profile is None:
        raise HTTPException(status_code=422, detail="Customer must be active in the selected organization")


async def _validate_assignee(context: TenantSessionContext, member_id: UUID | None) -> None:
    if member_id is None:
        return
    member = await context.session.scalar(select(WorkspaceMembership.id).where(
        WorkspaceMembership.tenant_id == context.access.tenant_id,
        WorkspaceMembership.id == member_id,
        WorkspaceMembership.status == "active",
    ))
    if member is None:
        raise HTTPException(status_code=422, detail="Assignee must be an active workspace member")


def _snapshot(item: CRMCustomerSupportCase) -> dict:
    return {
        "organization_unit_id": str(item.organization_unit_id),
        "profile_id": str(item.profile_id),
        "assigned_membership_id": str(item.assigned_membership_id) if item.assigned_membership_id else None,
        "subject": item.subject,
        "status": item.status,
        "priority": item.priority,
        "response_due_at": item.response_due_at.isoformat() if item.response_due_at else None,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
    }


def _audit(
    context: TenantSessionContext,
    item: CRMCustomerSupportCase,
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
        target_type="crm_support_case",
        target_key=str(item.id),
        organization_unit_id=item.organization_unit_id,
        before_state=before,
        after_state=after,
        correlation_id=None,
    ))


@router.post("", response_model=SupportCaseRead, status_code=201,
             operation_id="createCRMSupportCase")
async def create_support_case(
    payload: SupportCaseCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SupportCaseRead:
    await _require(context, "crm.support_case:create", payload.organization_unit_id)
    await _validate_profile(context, payload.organization_unit_id, payload.profile_id)
    await _validate_assignee(context, payload.assigned_membership_id)
    item = CRMCustomerSupportCase(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id, profile_id=payload.profile_id,
        assigned_membership_id=payload.assigned_membership_id,
        created_by_membership_id=context.access.membership_id,
        subject=payload.subject, description=payload.description, status="open",
        priority=payload.priority, response_due_at=payload.response_due_at,
        resolved_at=None,
    )
    context.session.add(item)
    await context.session.flush()
    _audit(context, item, "crm_support_case.created", None, _snapshot(item))
    await context.session.flush()
    return SupportCaseRead.model_validate(item)


@router.get("", response_model=SupportCasePage, operation_id="listCRMSupportCases")
async def list_support_cases(
    organization_unit_id: UUID,
    status: SupportCaseStatus | None = Query(default=None),
    priority: SupportCasePriority | None = Query(default=None),
    assigned_to_me: bool = False,
    overdue_only: bool = False,
    as_of: datetime = Query(default_factory=lambda: datetime.now(timezone.utc)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SupportCasePage:
    if as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    await _require(context, "crm.support_case:view", organization_unit_id)
    filters = [
        CRMCustomerSupportCase.tenant_id == context.access.tenant_id,
        CRMCustomerSupportCase.organization_unit_id == organization_unit_id,
    ]
    if status is not None:
        filters.append(CRMCustomerSupportCase.status == status)
    if priority is not None:
        filters.append(CRMCustomerSupportCase.priority == priority)
    if assigned_to_me:
        filters.append(CRMCustomerSupportCase.assigned_membership_id == context.access.membership_id)
    open_case = CRMCustomerSupportCase.status.in_(("open", "in_progress", "waiting_customer"))
    overdue_expr = open_case & CRMCustomerSupportCase.response_due_at.is_not(None) & (
        CRMCustomerSupportCase.response_due_at < as_of
    )
    overdue_count = int(await context.session.scalar(
        select(func.count()).select_from(CRMCustomerSupportCase).where(*filters, overdue_expr)
    ) or 0)
    if overdue_only:
        filters.append(overdue_expr)
    total = int(await context.session.scalar(
        select(func.count()).select_from(CRMCustomerSupportCase).where(*filters)
    ) or 0)
    priority_order = case(
        (CRMCustomerSupportCase.priority == "urgent", 0),
        (CRMCustomerSupportCase.priority == "high", 1),
        (CRMCustomerSupportCase.priority == "normal", 2),
        else_=3,
    )
    overdue_order = case((overdue_expr, 0), else_=1)
    rows = (await context.session.scalars(
        select(CRMCustomerSupportCase).where(*filters)
        .order_by(overdue_order, priority_order,
                  CRMCustomerSupportCase.response_due_at.asc().nullslast(),
                  CRMCustomerSupportCase.created_at.asc(), CRMCustomerSupportCase.id)
        .limit(limit).offset(offset)
    )).all()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_support_case.queue_viewed",
        target_type="crm_support_case_queue", target_key=str(organization_unit_id),
        organization_unit_id=organization_unit_id, before_state=None,
        after_state={"status": status, "priority": priority,
            "assigned_to_me": assigned_to_me, "overdue_only": overdue_only,
            "as_of": as_of.isoformat(), "total": total, "overdue_count": overdue_count,
            "limit": limit, "offset": offset, "returned": len(rows)},
        correlation_id=None,
    ))
    await context.session.flush()
    return SupportCasePage(
        items=[SupportCaseRead.model_validate(row) for row in rows],
        total=total, overdue_count=overdue_count, limit=limit, offset=offset,
    )


@router.patch("/{case_id}", response_model=SupportCaseRead,
              operation_id="updateCRMSupportCase")
async def update_support_case(
    case_id: UUID,
    payload: SupportCaseUpdate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SupportCaseRead:
    item = await context.session.scalar(select(CRMCustomerSupportCase).where(
        CRMCustomerSupportCase.tenant_id == context.access.tenant_id,
        CRMCustomerSupportCase.id == case_id,
    ).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="CRM support case not found")
    await _require(context, "crm.support_case:update", item.organization_unit_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field must be provided")
    if item.status == "closed":
        raise HTTPException(status_code=409, detail="Closed support cases cannot be changed")
    next_status = changes.get("status", item.status)
    allowed = {
        "open": {"open", "in_progress", "waiting_customer", "resolved", "closed"},
        "in_progress": {"in_progress", "waiting_customer", "resolved", "closed"},
        "waiting_customer": {"waiting_customer", "in_progress", "resolved", "closed"},
        "resolved": {"resolved", "open", "closed"},
    }
    if next_status not in allowed[item.status]:
        raise HTTPException(status_code=409, detail="Invalid support case status transition")
    if "assigned_membership_id" in changes:
        await _validate_assignee(context, changes["assigned_membership_id"])
    before = _snapshot(item)
    for key, value in changes.items():
        setattr(item, key, value)
    item.resolved_at = (
        item.resolved_at or datetime.now(timezone.utc)
        if next_status in {"resolved", "closed"} else None
    )
    item.status = next_status
    item.updated_at = datetime.now(timezone.utc)
    await context.session.flush()
    _audit(context, item, "crm_support_case.updated", before, _snapshot(item))
    await context.session.flush()
    return SupportCaseRead.model_validate(item)
