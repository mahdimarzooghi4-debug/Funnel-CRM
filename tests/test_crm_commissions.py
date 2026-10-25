from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select

from funnel_crm.api.v1.crm_commissions import router as commissions_router
from funnel_crm.api.v1.crm_workspace_context import router as workspace_context_router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMCommissionCalculation,
    CRMCommissionCalculationRow,
    CRMProductCommerceEvent,
    Role,
    RoleAssignment,
    RolePermission,
    WorkspaceMembership,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(commissions_router, prefix="/api/v1")
    app.include_router(workspace_context_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_commission_plan_creation_requires_manage_permission(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id, org_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(identity, AuthenticatedIdentity)
    app = make_app(runtime_session_factory, identity)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/crm/commission-plans",
            headers={"X-Workspace-ID": str(tenant_id)},
            json={
                "organization_unit_id": str(org_id),
                "name": "Unauthorized plan",
                "rate_percent": "10",
            },
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_commission_plan_calculation_keeps_currency_refunds_and_unattributed_separate(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id, org_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    identity_b = tenant_case["identity_b"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(org_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    assert isinstance(identity_b, AuthenticatedIdentity)
    period_date = datetime.now(timezone.utc).date()
    calculation_request_id = uuid4()
    event_time = datetime.combine(period_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=12)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_case["workspace_b"],
        identity=identity_b,
    ) as other_context:
        other_identity_id = other_context.access.identity_id

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        seller_id = context.access.membership_id
        role = Role(tenant_id=tenant_id, name=f"Commission manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=seller_id,
                role_id=role.id, organization_unit_id=org_id,
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id,
                permission_key="crm.commission:manage",
            ),
            RolePermission(
                tenant_id=tenant_id, role_id=role.id,
                permission_key="crm.commission:view",
            ),
        ])
        other_membership = WorkspaceMembership(
            tenant_id=tenant_id, identity_id=other_identity_id, status="active",
        )
        context.session.add(other_membership)
        await context.session.flush()
        other_seller_id = other_membership.id
        event_ids = [uuid4() for _ in range(5)]
        events = [
            (seller_id, "paid", "100", "USD"),
            (seller_id, "refunded", "15", "USD"),
            (None, "paid", "50", "USD"),
            (seller_id, "paid", "20", "EUR"),
            (other_seller_id, "paid", "200", "USD"),
        ]
        for source_event_id, (event_seller, kind, amount, currency) in zip(event_ids, events):
            context.session.add(CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=org_id,
                campaign_id=None, profile_id=None, seller_membership_id=event_seller,
                source_product="funnel.store", source_event_id=source_event_id,
                event_type=f"commerce.order.{kind}", order_reference=f"ORDER-{source_event_id}",
                event_kind=kind, amount=Decimal(amount), currency=currency,
                occurred_at=event_time,
            ))
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        plan_response = await client.post(
            "/api/v1/crm/commission-plans", headers=headers,
            json={
                "organization_unit_id": str(org_id),
                "name": "Store sales",
                "rate_percent": "10",
            },
        )
        assert plan_response.status_code == 201, plan_response.text
        plan_id = plan_response.json()["id"]
        commission_units = await client.get(
            "/api/v1/system/commission-organization-units", headers=headers
        )
        assert commission_units.status_code == 200, commission_units.text
        assert {unit["id"] for unit in commission_units.json()} == {str(org_id)}

        calculation_response = await client.post(
            f"/api/v1/crm/commission-plans/{plan_id}/calculations",
            headers=headers,
            json={"period_start": period_date.isoformat(), "period_end": period_date.isoformat(),
                  "request_id": str(calculation_request_id)},
        )
        assert calculation_response.status_code == 201, calculation_response.text
        calculation = calculation_response.json()
        assert calculation["plan_version"] == 1
        assert calculation["status"] == "calculation_only"
        assert calculation["timezone"] == "UTC"
        assert calculation["money_transfer_or_payroll_instruction_created"] is False
        by_currency_seller = {
            (row["seller_membership_id"], row["currency"]): row
            for row in calculation["rows"]
        }
        attributed_usd = by_currency_seller[(str(seller_id), "USD")]
        assert Decimal(attributed_usd["paid_amount"]) == Decimal("100.000000")
        assert Decimal(attributed_usd["refunded_amount"]) == Decimal("15.000000")
        assert Decimal(attributed_usd["net_amount"]) == Decimal("85.000000")
        assert Decimal(attributed_usd["commission_amount"]) == Decimal("8.500000")
        attributed_eur = by_currency_seller[(str(seller_id), "EUR")]
        assert Decimal(attributed_eur["commission_amount"]) == Decimal("2.000000")
        unattributed = by_currency_seller[(None, "USD")]
        assert unattributed["unattributed"] is True
        assert unattributed["excluded_from_commission"] is True
        assert Decimal(unattributed["paid_amount"]) == Decimal("50.000000")
        assert Decimal(unattributed["commission_amount"]) == Decimal("0.000000")
        assert set(unattributed["source_event_ids"]) == {str(event_ids[2])}
        other_seller_row = by_currency_seller[(str(other_seller_id), "USD")]
        assert Decimal(other_seller_row["commission_amount"]) == Decimal("20.000000")

        duplicate_calculation = await client.post(
            f"/api/v1/crm/commission-plans/{plan_id}/calculations",
            headers=headers,
            json={"period_start": period_date.isoformat(), "period_end": period_date.isoformat(),
                  "request_id": str(calculation_request_id)},
        )
        assert duplicate_calculation.status_code == 201, duplicate_calculation.text
        assert duplicate_calculation.json()["id"] == calculation["id"]
        assert duplicate_calculation.json()["rows"] == calculation["rows"]
        conflicting_retry = await client.post(
            f"/api/v1/crm/commission-plans/{plan_id}/calculations",
            headers=headers,
            json={"period_start": (period_date - timedelta(days=1)).isoformat(),
                  "period_end": period_date.isoformat(),
                  "request_id": str(calculation_request_id)},
        )
        assert conflicting_retry.status_code == 409

        updated_plan = await client.patch(
            f"/api/v1/crm/commission-plans/{plan_id}", headers=headers,
            json={"expected_version": 1, "rate_percent": "12"},
        )
        assert updated_plan.status_code == 200, updated_plan.text
        assert updated_plan.json()["version"] == 2
        stale_update = await client.patch(
            f"/api/v1/crm/commission-plans/{plan_id}", headers=headers,
            json={"expected_version": 1, "rate_percent": "15"},
        )
        assert stale_update.status_code == 409
        replay_after_plan_change = await client.post(
            f"/api/v1/crm/commission-plans/{plan_id}/calculations",
            headers=headers,
            json={"period_start": period_date.isoformat(), "period_end": period_date.isoformat(),
                  "request_id": str(calculation_request_id)},
        )
        assert replay_after_plan_change.status_code == 201
        assert replay_after_plan_change.json()["id"] == calculation["id"]
        assert replay_after_plan_change.json()["plan_version"] == 1
        revised_calculation_response = await client.post(
            f"/api/v1/crm/commission-plans/{plan_id}/calculations",
            headers=headers,
            json={"period_start": period_date.isoformat(), "period_end": period_date.isoformat()},
        )
        assert revised_calculation_response.status_code == 201, revised_calculation_response.text
        revised_calculation = revised_calculation_response.json()
        assert revised_calculation["plan_version"] == 2
        revised_by_currency = {
            (row["seller_membership_id"], row["currency"]): row
            for row in revised_calculation["rows"]
        }
        assert Decimal(revised_by_currency[(str(seller_id), "USD")] ["commission_amount"]) == Decimal("10.200000")

        plan_versions = await client.get(
            f"/api/v1/crm/commission-plans/{plan_id}/versions", headers=headers
        )
        assert plan_versions.status_code == 200, plan_versions.text
        versions_by_number = {
            item["version"]: item for item in plan_versions.json()["items"]
        }
        assert set(versions_by_number) == {1, 2}
        assert Decimal(versions_by_number[1]["rate_percent"]) == Decimal("10.0000")
        assert Decimal(versions_by_number[2]["rate_percent"]) == Decimal("12.0000")

        history = await client.get(
            f"/api/v1/crm/commission-plans/{plan_id}/calculations", headers=headers
        )
        assert history.status_code == 200, history.text
        assert len(history.json()["items"]) == 2
        historical_versions = {item["plan_version"] for item in history.json()["items"]}
        assert historical_versions == {1, 2}
        assert len(history.json()["items"][0]["rows"]) == 4

        seller_plan_response = await client.post(
            "/api/v1/crm/commission-plans", headers=headers,
            json={
                "organization_unit_id": str(org_id),
                "seller_membership_id": str(seller_id),
                "name": "Individual seller",
                "rate_percent": "20",
            },
        )
        assert seller_plan_response.status_code == 201, seller_plan_response.text
        seller_plan_id = seller_plan_response.json()["id"]
        async with tenant_session(
            runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
        ) as context:
            inactive_seller = await context.session.get(WorkspaceMembership, other_seller_id)
            assert inactive_seller is not None
            inactive_seller.status = "suspended"
        inactive_plan_response = await client.post(
            "/api/v1/crm/commission-plans", headers=headers,
            json={
                "organization_unit_id": str(org_id),
                "seller_membership_id": str(other_seller_id),
                "name": "Inactive seller plan",
                "rate_percent": "10",
            },
        )
        assert inactive_plan_response.status_code == 422
        async with tenant_session(
            runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
        ) as context:
            inactive_seller = await context.session.get(WorkspaceMembership, other_seller_id)
            assert inactive_seller is not None
            inactive_seller.status = "active"
        seller_calculation_response = await client.post(
            f"/api/v1/crm/commission-plans/{seller_plan_id}/calculations",
            headers=headers,
            json={"period_start": period_date.isoformat(), "period_end": period_date.isoformat()},
        )
        assert seller_calculation_response.status_code == 201, seller_calculation_response.text
        seller_calculation = seller_calculation_response.json()
        seller_rows = {
            (row["seller_membership_id"], row["currency"]): row
            for row in seller_calculation["rows"]
        }
        assert set(seller_rows) == {(str(seller_id), "USD"), (str(seller_id), "EUR"), (None, "USD")}
        assert Decimal(seller_rows[(str(seller_id), "USD")]["commission_amount"]) == Decimal("17.000000")
        assert Decimal(seller_rows[(None, "USD")]["commission_amount"]) == Decimal("0.000000")
        assert all(
            str(event_ids[4]) not in row["source_event_ids"]
            for row in seller_calculation["rows"]
        )

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        snapshot = await context.session.scalar(select(CRMCommissionCalculation).where(
            CRMCommissionCalculation.tenant_id == tenant_id,
            CRMCommissionCalculation.plan_id == UUID(plan_id),
        ))
        assert snapshot is not None
        rows = list(await context.session.scalars(select(CRMCommissionCalculationRow).where(
            CRMCommissionCalculationRow.tenant_id == tenant_id,
            CRMCommissionCalculationRow.calculation_id == snapshot.id,
        )))
        assert len(rows) == 4
        audit_actions = list(await context.session.scalars(select(AuditEvent.action_key).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action_key.in_({
                "crm_commission.plan_created", "crm_commission.plan_updated",
                "crm_commission.calculation_created",
            }),
        )))
        assert set(audit_actions) == {
            "crm_commission.plan_created", "crm_commission.plan_updated",
            "crm_commission.calculation_created",
        }
