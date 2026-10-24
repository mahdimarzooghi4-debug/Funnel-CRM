"""Organization-scoped customer support cases and response work queue."""

from datetime import date, datetime, timedelta, timezone
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
    CRMCustomerSupportCaseEntry,
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
    first_response_at: datetime | None
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
        "first_response_at": item.first_response_at.isoformat() if item.first_response_at else None,
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
        first_response_at=None, resolved_at=None,
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


class SupportCaseEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_kind: Literal["internal_note", "response_record"]
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def clean_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("body must not be blank")
        return value


class SupportCaseEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    support_case_id: UUID
    author_membership_id: UUID
    entry_kind: Literal["internal_note", "response_record"]
    body: str
    created_at: datetime


class SupportCaseEntryPage(BaseModel):
    items: list[SupportCaseEntryRead]
    total: int
    limit: int
    offset: int


class SupportCaseSLAReport(BaseModel):
    period_start: date
    period_end: date
    as_of: datetime
    case_count: int
    active_case_count: int
    overdue_open_count: int
    cases_with_response_deadline: int
    first_response_recorded_count: int
    on_time_first_response_count: int
    late_first_response_count: int
    awaiting_first_response_count: int
    first_response_sla_rate_percent: float | None


@router.post("/{case_id}/entries", response_model=SupportCaseEntryRead,
             status_code=201, operation_id="createCRMSupportCaseEntry")
async def create_support_case_entry(
    case_id: UUID,
    payload: SupportCaseEntryCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SupportCaseEntryRead:
    item = await context.session.scalar(select(CRMCustomerSupportCase).where(
        CRMCustomerSupportCase.tenant_id == context.access.tenant_id,
        CRMCustomerSupportCase.id == case_id,
    ).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="CRM support case not found")
    await _require(context, "crm.support_case:update", item.organization_unit_id)
    if item.status == "closed":
        raise HTTPException(status_code=409, detail="Closed support cases cannot receive entries")
    if payload.entry_kind == "response_record" and item.status == "resolved":
        raise HTTPException(status_code=409, detail="Reopen the case before recording a response")
    now = datetime.now(timezone.utc)
    entry = CRMCustomerSupportCaseEntry(
        id=uuid4(), tenant_id=context.access.tenant_id, support_case_id=item.id,
        author_membership_id=context.access.membership_id,
        entry_kind=payload.entry_kind, body=payload.body,
    )
    context.session.add(entry)
    if payload.entry_kind == "response_record" and item.first_response_at is None:
        before = _snapshot(item)
        item.first_response_at = now
        item.updated_at = now
        await context.session.flush()
        _audit(context, item, "crm_support_case.first_response_recorded", before, _snapshot(item))
    await context.session.flush()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_support_case.entry_added", target_type="crm_support_case_entry",
        target_key=str(entry.id), organization_unit_id=item.organization_unit_id,
        before_state=None,
        after_state={"support_case_id": str(item.id), "entry_kind": entry.entry_kind},
        correlation_id=None,
    ))
    await context.session.flush()
    return SupportCaseEntryRead.model_validate(entry)


@router.get("/{case_id}/entries", response_model=SupportCaseEntryPage,
            operation_id="listCRMSupportCaseEntries")
async def list_support_case_entries(
    case_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SupportCaseEntryPage:
    item = await context.session.scalar(select(CRMCustomerSupportCase).where(
        CRMCustomerSupportCase.tenant_id == context.access.tenant_id,
        CRMCustomerSupportCase.id == case_id,
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="CRM support case not found")
    await _require(context, "crm.support_case:view", item.organization_unit_id)
    filters = [
        CRMCustomerSupportCaseEntry.tenant_id == context.access.tenant_id,
        CRMCustomerSupportCaseEntry.support_case_id == item.id,
    ]
    total = int(await context.session.scalar(
        select(func.count()).select_from(CRMCustomerSupportCaseEntry).where(*filters)
    ) or 0)
    rows = (await context.session.scalars(
        select(CRMCustomerSupportCaseEntry).where(*filters)
        .order_by(CRMCustomerSupportCaseEntry.created_at, CRMCustomerSupportCaseEntry.id)
        .limit(limit).offset(offset)
    )).all()
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_support_case.entries_viewed",
        target_type="crm_support_case_entry_collection", target_key=str(item.id),
        organization_unit_id=item.organization_unit_id, before_state=None,
        after_state={"total": total, "returned": len(rows), "limit": limit, "offset": offset},
        correlation_id=None,
    ))
    await context.session.flush()
    return SupportCaseEntryPage(
        items=[SupportCaseEntryRead.model_validate(row) for row in rows],
        total=total, limit=limit, offset=offset,
    )


@router.get("/reports/sla", response_model=SupportCaseSLAReport,
            operation_id="getCRMSupportCaseSLAReport")
async def get_support_case_sla_report(
    organization_unit_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    as_of: datetime = Query(default_factory=lambda: datetime.now(timezone.utc)),
    context: TenantSessionContext = Depends(require_tenant_session),
) -> SupportCaseSLAReport:
    if period_start > period_end or (period_end - period_start).days > 365:
        raise HTTPException(status_code=422, detail="SLA report period must be ordered and no longer than 366 days")
    if as_of.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    await _require(context, "crm.support_case:view", organization_unit_id)
    start_at = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
    end_at = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    active = CRMCustomerSupportCase.status.in_(("open", "in_progress", "waiting_customer"))
    due = CRMCustomerSupportCase.response_due_at.is_not(None)
    has_first_response = CRMCustomerSupportCase.first_response_at.is_not(None)
    counts = (await context.session.execute(select(
        func.count(CRMCustomerSupportCase.id),
        func.sum(case((active, 1), else_=0)),
        func.sum(case((active & due & (CRMCustomerSupportCase.response_due_at < as_of), 1), else_=0)),
        func.sum(case((due, 1), else_=0)),
        func.sum(case((due & has_first_response, 1), else_=0)),
        func.sum(case((due & has_first_response & (
            CRMCustomerSupportCase.first_response_at <= CRMCustomerSupportCase.response_due_at
        ), 1), else_=0)),
        func.sum(case((due & has_first_response & (
            CRMCustomerSupportCase.first_response_at > CRMCustomerSupportCase.response_due_at
        ), 1), else_=0)),
        func.sum(case((active & due & ~has_first_response, 1), else_=0)),
    ).where(
        CRMCustomerSupportCase.tenant_id == context.access.tenant_id,
        CRMCustomerSupportCase.organization_unit_id == organization_unit_id,
        CRMCustomerSupportCase.created_at >= start_at,
        CRMCustomerSupportCase.created_at < end_at,
    ))).one()
    total, active_count, overdue, due_count, responded, on_time, late, awaiting = (
        int(value or 0) for value in counts
    )
    rate = round(on_time * 100.0 / responded, 2) if responded else None
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id, actor_kind="user",
        actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_support_case.sla_report_viewed",
        target_type="crm_support_case_sla_report",
        target_key=str(organization_unit_id), organization_unit_id=organization_unit_id,
        before_state=None, after_state={
            "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
            "case_count": total, "overdue_open_count": overdue,
            "first_response_recorded_count": responded,
            "on_time_first_response_count": on_time, "late_first_response_count": late,
        }, correlation_id=None,
    ))
    await context.session.flush()
    return SupportCaseSLAReport(
        period_start=period_start, period_end=period_end, as_of=as_of,
        case_count=total, active_case_count=active_count, overdue_open_count=overdue,
        cases_with_response_deadline=due_count, first_response_recorded_count=responded,
        on_time_first_response_count=on_time, late_first_response_count=late,
        awaiting_first_response_count=awaiting, first_response_sla_rate_percent=rate,
    )
