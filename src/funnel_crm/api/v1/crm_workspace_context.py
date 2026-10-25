"""Identity-scoped CRM workspace and organization selectors."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids
from funnel_crm.platform.models import OrganizationUnit, UserIdentity, Workspace, WorkspaceMembership
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, TenantSessionContext

router = APIRouter(prefix="/system", tags=["identity workspace context"])


class WorkspaceChoice(BaseModel):
    id: UUID
    membership_id: UUID
    name: str
    root_organization_id: UUID


class OrganizationUnitChoice(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None
    unit_type: str


@router.get("/workspaces", response_model=list[WorkspaceChoice])
async def list_current_user_workspaces(request: Request) -> list[WorkspaceChoice]:
    """Return active memberships for the identity verified by upstream auth."""
    identity = getattr(request.state, "authenticated_identity", None)
    if not isinstance(identity, AuthenticatedIdentity):
        raise HTTPException(status_code=401, detail="Authentication required")
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Workspace data service is unavailable")
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "SELECT set_config('app.authenticated_issuer', :issuer, true), "
                    "set_config('app.authenticated_subject', :subject, true)"
                ),
                {"issuer": identity.issuer, "subject": identity.subject},
            )
            rows = (
                await session.execute(
                    select(Workspace.id, WorkspaceMembership.id, Workspace.display_name, Workspace.root_organization_id)
                    .join(
                        WorkspaceMembership,
                        WorkspaceMembership.tenant_id == Workspace.id,
                    )
                    .join(
                        UserIdentity,
                        UserIdentity.id == WorkspaceMembership.identity_id,
                    )
                    .where(
                        WorkspaceMembership.status == "active",
                        UserIdentity.issuer == identity.issuer,
                        UserIdentity.subject == identity.subject,
                    )
                    .order_by(Workspace.display_name, Workspace.id)
                )
            ).all()
    return [
        WorkspaceChoice(id=row.id, membership_id=row[1], name=row.display_name,
                        root_organization_id=row.root_organization_id)
        for row in rows
    ]


@router.get("/organization-units", response_model=list[OrganizationUnitChoice])
async def list_authorized_organization_units(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[OrganizationUnitChoice]:
    """Return units covered by both campaign and budget-scenario view grants."""
    campaign_scopes = crm_scope_ids(
        context,
        permission_key="crm.campaign:view",
        cte_name="crm_campaign_selector_scope",
    )
    scenario_scopes = crm_scope_ids(
        context,
        permission_key="crm.budget_scenario:view",
        cte_name="crm_budget_scenario_selector_scope",
    )
    rows = (
        await context.session.scalars(
            select(OrganizationUnit)
            .where(
                OrganizationUnit.tenant_id == context.access.tenant_id,
                OrganizationUnit.id.in_(campaign_scopes),
                OrganizationUnit.id.in_(scenario_scopes),
            )
            .order_by(OrganizationUnit.name, OrganizationUnit.id)
        )
    ).all()
    return [
        OrganizationUnitChoice(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            unit_type=row.unit_type,
        )
        for row in rows
    ]


@router.get("/commission-organization-units", response_model=list[OrganizationUnitChoice])
async def list_commission_organization_units(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[OrganizationUnitChoice]:
    """Return only organization units where this user may view commissions."""
    scopes = crm_scope_ids(
        context,
        permission_key="crm.commission:view",
        cte_name="crm_commission_selector_scope",
    )
    rows = (
        await context.session.scalars(
            select(OrganizationUnit)
            .where(
                OrganizationUnit.tenant_id == context.access.tenant_id,
                OrganizationUnit.id.in_(scopes),
            )
            .order_by(OrganizationUnit.name, OrganizationUnit.id)
        )
    ).all()
    return [
        OrganizationUnitChoice(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            unit_type=row.unit_type,
        )
        for row in rows
    ]


@router.get("/catalog-organization-units", response_model=list[OrganizationUnitChoice])
async def list_catalog_organization_units(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[OrganizationUnitChoice]:
    """Return organization units where this user may view the product catalog."""
    scopes = crm_scope_ids(
        context,
        permission_key="crm.catalog:view",
        cte_name="crm_catalog_selector_scope",
    )
    rows = (
        await context.session.scalars(
            select(OrganizationUnit)
            .where(
                OrganizationUnit.tenant_id == context.access.tenant_id,
                OrganizationUnit.id.in_(scopes),
            )
            .order_by(OrganizationUnit.name, OrganizationUnit.id)
        )
    ).all()
    return [
        OrganizationUnitChoice(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            unit_type=row.unit_type,
        )
        for row in rows
    ]


@router.get("/opportunity-organization-units", response_model=list[OrganizationUnitChoice])
async def list_opportunity_organization_units(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[OrganizationUnitChoice]:
    """Return organization units where this user may view sales opportunities."""
    scopes = crm_scope_ids(
        context,
        permission_key="crm.opportunity:view",
        cte_name="crm_opportunity_selector_scope",
    )
    rows = (await context.session.scalars(
        select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == context.access.tenant_id,
            OrganizationUnit.id.in_(scopes),
        ).order_by(OrganizationUnit.name, OrganizationUnit.id)
    )).all()
    return [OrganizationUnitChoice(id=row.id, name=row.name, parent_id=row.parent_id, unit_type=row.unit_type)
            for row in rows]


@router.get("/offer-plan-organization-units", response_model=list[OrganizationUnitChoice])
async def list_offer_plan_organization_units(
    context: TenantSessionContext = Depends(require_tenant_session),
) -> list[OrganizationUnitChoice]:
    """Return units where the current user can view marketing offer plans."""
    scopes = crm_scope_ids(
        context, permission_key="crm.offer_plan:view", cte_name="crm_offer_plan_selector_scope",
    )
    rows = (await context.session.scalars(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == context.access.tenant_id,
        OrganizationUnit.id.in_(scopes),
    ).order_by(OrganizationUnit.name, OrganizationUnit.id))).all()
    return [OrganizationUnitChoice(id=row.id, name=row.name, parent_id=row.parent_id, unit_type=row.unit_type)
            for row in rows]
