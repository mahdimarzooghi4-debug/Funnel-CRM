from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from funnel_crm.api.v1.crm_opportunities import router
from funnel_crm.api.v1.crm_sales_forecasting import router as forecast_router
from funnel_crm.api.v1.crm_catalog import router as catalog_router
from funnel_crm.api.v1.crm_opportunity_catalog import router as opportunity_catalog_router
from funnel_crm.api.v1.crm_opportunity_offers import router as opportunity_offers_router
from funnel_crm.api.v1.crm_offer_plans import router as offer_plans_router
from funnel_crm.api.v1.crm_offer_scenarios import router as offer_scenarios_router
from funnel_crm.platform.models import Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    app.include_router(forecast_router, prefix="/api/v1")
    app.include_router(catalog_router, prefix="/api/v1")
    app.include_router(opportunity_catalog_router, prefix="/api/v1")
    app.include_router(opportunity_offers_router, prefix="/api/v1")
    app.include_router(offer_plans_router, prefix="/api/v1")
    app.include_router(offer_scenarios_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_sales_pipeline_and_opportunity_board_are_scoped_and_audited(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        role = Role(tenant_id=tenant_id, name=f"Opportunity manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id,
                membership_id=context.access.membership_id,
                role_id=role.id,
                organization_unit_id=root_id,
            ),
            *[
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key=permission,
                )
                for permission in (
                    "crm.pipeline:manage",
                    "crm.opportunity:view",
                    "crm.opportunity:create",
                    "crm.opportunity:update",
                    "crm.catalog:view",
                    "crm.catalog:manage",
                    "crm.offer:view",
                    "crm.offer:create",
                    "crm.offer_plan:view",
                    "crm.offer_plan:create",
                    "crm.offer_plan:update",
                    "crm.offer_plan:approve",
                    "crm.offer_plan:scenario",
                )
            ],
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        pipeline = await client.post(
            "/api/v1/crm/opportunities/pipelines",
            headers=headers,
            json={
                "pipeline_key": f"retail-{uuid4().hex[:6]}",
                "display_name": "Retail sales",
                "is_default": True,
                "stages": [
                    {"key": "qualified", "name": "Qualified", "position": 1},
                    {"key": "proposal", "name": "Proposal", "position": 2},
                    {"key": "won", "name": "Won", "position": 3, "outcome_key": "won"},
                    {"key": "lost", "name": "Lost", "position": 4, "outcome_key": "lost"},
                ],
            },
        )
        assert pipeline.status_code == 201, pipeline.text
        pipeline_id = pipeline.json()["id"]

        probability = await client.patch(
            f"/api/v1/crm/sales-forecast/pipelines/{pipeline_id}/stages/qualified/probability",
            headers=headers,
            json={"probability_percent": 60},
        )
        assert probability.status_code == 200, probability.text
        assert probability.json()["probability_percent"] == 60

        invalid_probability = await client.patch(
            f"/api/v1/crm/sales-forecast/pipelines/{pipeline_id}/stages/qualified/probability",
            headers=headers,
            json={"probability_percent": 101},
        )
        assert invalid_probability.status_code == 422

        created = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Central store rollout",
                "stage_key": "qualified",
                "amount": "12500.00",
                "currency": "USD",
                "expected_close_date": "2026-12-01",
            },
        )
        assert created.status_code == 201, created.text
        opportunity_id = created.json()["id"]

        catalog_item = await client.post(
            "/api/v1/crm/catalog/items", headers=headers,
            json={"organization_unit_id": str(root_id), "code": "OFFER-01",
                  "name": "Retail onboarding", "item_type": "service", "category": "Services"},
        )
        assert catalog_item.status_code == 201, catalog_item.text
        attached = await client.post(
            f"/api/v1/crm/opportunities/{opportunity_id}/catalog-items", headers=headers,
            json={"catalog_item_id": catalog_item.json()["id"],
                  "expected_catalog_version": catalog_item.json()["version"]},
        )
        assert attached.status_code == 201, attached.text
        assert attached.json()["name"] == "Retail onboarding"
        assert attached.json()["category"] == "Services"
        item_list = await client.get(
            f"/api/v1/crm/opportunities/{opportunity_id}/catalog-items", headers=headers,
        )
        assert [row["id"] for row in item_list.json()["items"]] == [attached.json()["id"]]
        duplicate_link = await client.post(
            f"/api/v1/crm/opportunities/{opportunity_id}/catalog-items", headers=headers,
            json={"catalog_item_id": catalog_item.json()["id"], "expected_catalog_version": 1},
        )
        assert duplicate_link.status_code == 409
        price = await client.post(
            f"/api/v1/crm/catalog/items/{catalog_item.json()['id']}/prices",
            headers=headers, json={"amount": "250.00", "currency": "USD"},
        )
        assert price.status_code == 201, price.text
        offer = await client.post(
            f"/api/v1/crm/opportunities/{opportunity_id}/offer-drafts", headers=headers,
            json={"lines": [{"catalog_item_id": catalog_item.json()["id"],
                             "expected_catalog_version": 1,
                             "price_version": price.json()["version"], "quantity": "2"}]},
        )
        assert offer.status_code == 201, offer.text
        assert offer.json()["status"] == "draft"
        assert offer.json()["lines"][0]["unit_amount"] == "250.000000"
        assert offer.json()["totals_by_currency"] == {"USD": "500.000000"}
        revised_offer = await client.post(
            f"/api/v1/crm/opportunities/{opportunity_id}/offer-drafts/{offer.json()['id']}/revisions",
            headers=headers,
            json={"lines": [{"catalog_item_id": catalog_item.json()["id"],
                             "expected_catalog_version": 1,
                             "price_version": price.json()["version"], "quantity": "3"}]},
        )
        assert revised_offer.status_code == 201, revised_offer.text
        assert revised_offer.json()["revision_number"] == 2
        assert revised_offer.json()["previous_revision_id"] == offer.json()["id"]
        assert revised_offer.json()["totals_by_currency"] == {"USD": "750.000000"}
        stale_revision = await client.post(
            f"/api/v1/crm/opportunities/{opportunity_id}/offer-drafts/{offer.json()['id']}/revisions",
            headers=headers,
            json={"lines": [{"catalog_item_id": catalog_item.json()["id"],
                             "expected_catalog_version": 1,
                             "price_version": price.json()["version"], "quantity": "4"}]},
        )
        assert stale_revision.status_code == 409
        offer_list = await client.get(
            f"/api/v1/crm/opportunities/{opportunity_id}/offer-drafts", headers=headers,
        )
        assert {entry["id"] for entry in offer_list.json()["items"]} == {
            offer.json()["id"], revised_offer.json()["id"],
        }

        planned_offer = await client.post(
            "/api/v1/crm/offer-plans", headers=headers,
            json={"organization_unit_id": str(root_id), "name": "Retail launch offer",
                  "objective": "Increase first-month customer conversion",
                  "offer_type": "store-defined incentive", "catalog_item_id": catalog_item.json()["id"],
                  "audience_description": "New customers in assigned stores", "channel": "store",
                  "location_scope": "Central region", "eligibility_conditions": "First purchase only",
                  "success_metric": "First purchase conversion"},
        )
        assert planned_offer.status_code == 201, planned_offer.text
        assert planned_offer.json()["status"] == "draft"
        assert planned_offer.json()["version"] == 1
        scenario = await client.post(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}/scenarios", headers=headers,
            json={"name": "Low uptake", "audience_size": 80, "expected_use_rate": "12.5",
                  "price_version": price.json()["version"], "offer_value_per_use": "25",
                  "campaign_budget_amount": "100", "campaign_budget_currency": "USD",
                  "assumptions": "Take-up is 12.5%; each use generates one sale."},
        )
        assert scenario.status_code == 201, scenario.text
        scenario_data = scenario.json()
        assert scenario_data["plan_version"] == 1
        assert scenario_data["expected_uses"] == "10.0"
        assert scenario_data["gross_reference_revenue"] == "2500.000000"
        assert scenario_data["planned_offer_value"] == "250.000000"
        assert scenario_data["revenue_after_offer"] == "2250.000000"
        assert scenario_data["revenue_after_offer_and_campaign_budget"] == "2150.000000"
        assert scenario_data["margin_estimate"] is None
        listed_scenarios = await client.get(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}/scenarios", headers=headers,
        )
        assert [x["id"] for x in listed_scenarios.json()["items"]] == [scenario_data["id"]]
        plan_list = await client.get("/api/v1/crm/offer-plans", headers=headers,
                                     params={"organization_unit_id": str(root_id)})
        assert plan_list.status_code == 200, plan_list.text
        assert [item["id"] for item in plan_list.json()["items"]] == [planned_offer.json()["id"]]
        plan_update = await client.patch(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}", headers=headers,
            json={"expected_version": 1, "eligibility_conditions": "First purchase from an assigned store"},
        )
        assert plan_update.status_code == 200, plan_update.text
        assert plan_update.json()["version"] == 2
        requested_changes = await client.post(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}/decision", headers=headers,
            json={"expected_version": 2, "decision": "request_changes", "comment": "Clarify the audience."},
        )
        assert requested_changes.status_code == 200, requested_changes.text
        assert requested_changes.json()["status"] == "changes_requested"
        revised_plan = await client.patch(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}", headers=headers,
            json={"expected_version": 3, "audience_description": "New customers at assigned stores"},
        )
        assert revised_plan.status_code == 200, revised_plan.text
        assert revised_plan.json()["status"] == "draft"
        approved_plan = await client.post(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}/decision", headers=headers,
            json={"expected_version": 4, "decision": "approve", "comment": "Reviewed for the CRM plan."},
        )
        assert approved_plan.status_code == 200, approved_plan.text
        assert approved_plan.json()["status"] == "approved"
        stale_plan_update = await client.patch(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}", headers=headers,
            json={"expected_version": 5, "objective": "Approved plans are locked"},
        )
        assert stale_plan_update.status_code == 409
        approved_scenario = await client.post(
            f"/api/v1/crm/offer-plans/{planned_offer.json()['id']}/scenarios", headers=headers,
            json={"name": "After approval", "audience_size": 10, "expected_use_rate": 50,
                  "assumptions": "This must be rejected."},
        )
        assert approved_scenario.status_code == 409

        board = await client.get(
            "/api/v1/crm/opportunities",
            headers=headers,
            params={"stage_key": "qualified"},
        )
        assert board.status_code == 200, board.text
        assert board.json()["total"] == 1
        assert board.json()["items"][0]["id"] == opportunity_id

        moved = await client.patch(
            f"/api/v1/crm/opportunities/{opportunity_id}",
            headers=headers,
            json={"stage_key": "proposal", "amount": "13250.00", "currency": "USD"},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["stage_key"] == "proposal"
        assert moved.json()["amount"] == "13250.00"

        history = await client.get(
            f"/api/v1/crm/opportunities/{opportunity_id}/history",
            headers=headers,
            params={"limit": 1},
        )
        assert history.status_code == 200, history.text
        history_page = history.json()
        assert history_page["opportunity_id"] == opportunity_id
        assert history_page["total"] == 3
        assert len(history_page["items"]) == 1
        latest_event = history_page["items"][0]
        assert latest_event["action_key"] == "crm_opportunity.updated"
        assert latest_event["from_stage_key"] == "qualified"
        assert latest_event["to_stage_key"] == "proposal"
        assert latest_event["changed_fields"] == ["stage_key", "amount"]
        history_first_page = await client.get(
            f"/api/v1/crm/opportunities/{opportunity_id}/history",
            headers=headers,
            params={"limit": 10},
        )
        assert history_first_page.status_code == 200, history_first_page.text
        created_event = history_first_page.json()["items"][-1]
        assert created_event["action_key"] == "crm_opportunity.created"
        assert created_event["from_stage_key"] is None
        assert created_event["to_stage_key"] == "qualified"

        euro_opportunity = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "West region retail order",
                "stage_key": "qualified",
                "amount": "2000",
                "currency": "EUR",
                "expected_close_date": "2026-12-15",
            },
        )
        assert euro_opportunity.status_code == 201, euro_opportunity.text
        unpriced_opportunity = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Retail consultation",
                "stage_key": "qualified",
                "expected_close_date": "2026-12-20",
            },
        )
        assert unpriced_opportunity.status_code == 201, unpriced_opportunity.text
        unscheduled_opportunity = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Unscheduled sales lead",
                "stage_key": "qualified",
                "amount": "100",
                "currency": "EUR",
            },
        )
        assert unscheduled_opportunity.status_code == 201, unscheduled_opportunity.text

        worklist = await client.get(
            "/api/v1/crm/opportunities/worklist",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "as_of": "2026-12-10",
                "days_ahead": 7,
                "limit": 2,
            },
        )
        assert worklist.status_code == 200, worklist.text
        worklist_report = worklist.json()
        assert worklist_report["as_of"] == "2026-12-10"
        assert worklist_report["through_date"] == "2026-12-17"
        assert worklist_report["total"] == 4
        assert worklist_report["counts_by_state"] == {
            "overdue": 1, "due_soon": 1, "later": 1, "unscheduled": 1,
        }
        assert [item["date_state"] for item in worklist_report["items"]] == [
            "overdue", "due_soon",
        ]
        assert [item["days_until_expected_close"] for item in worklist_report["items"]] == [-9, 5]
        next_page = await client.get(
            "/api/v1/crm/opportunities/worklist",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "as_of": "2026-12-10",
                "days_ahead": 7,
                "limit": 2,
                "offset": 2,
            },
        )
        assert next_page.status_code == 200, next_page.text
        assert [item["date_state"] for item in next_page.json()["items"]] == [
            "later", "unscheduled",
        ]
        overdue_only = await client.get(
            "/api/v1/crm/opportunities/worklist",
            headers=headers,
            params={
                "as_of": "2026-12-10",
                "date_state": "overdue",
            },
        )
        assert overdue_only.status_code == 200, overdue_only.text
        assert overdue_only.json()["total"] == 1
        assert overdue_only.json()["counts_by_state"]["overdue"] == 1

        closed_won = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Retail expansion won",
                "stage_key": "won",
                "amount": "7000",
                "currency": "USD",
                "expected_close_date": "2026-12-20",
            },
        )
        assert closed_won.status_code == 201, closed_won.text
        closed_lost = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Retail expansion lost",
                "stage_key": "lost",
                "amount": "3000",
                "currency": "USD",
                "expected_close_date": "2026-12-21",
            },
        )
        assert closed_lost.status_code == 201, closed_lost.text

        forecast = await client.get(
            "/api/v1/crm/sales-forecast/opportunities",
            headers=headers,
            params={
                "pipeline_id": pipeline_id,
                "period_start": "2026-12-01",
                "period_end": "2026-12-31",
                "organization_unit_id": str(root_id),
            },
        )
        assert forecast.status_code == 200, forecast.text
        report = forecast.json()
        assert report["forecast_basis"] == "manager_configured_stage_probability"
        assert report["opportunity_count"] == 3
        assert report["closed_won_count"] == 1
        assert report["closed_lost_count"] == 1
        assert report["priced_opportunity_count"] == 2
        assert report["unpriced_opportunity_count"] == 1
        assert report["unknown_probability_opportunity_count"] == 1
        assert report["unscheduled_opportunity_count"] == 1
        assert report["weighted_expected_amount_by_currency"] == {"EUR": "1200.000000"}
        assert report["amount_without_probability_by_currency"] == {"USD": "13250.000000"}
        assert report["gross_amount_by_currency"] == {
            "EUR": "2000.000000", "USD": "13250.000000",
        }
        qualified = next(stage for stage in report["stages"] if stage["stage_key"] == "qualified")
        assert qualified["unpriced_opportunity_count"] == 1
        assert qualified["probability_percent"] == 60
        proposal = next(stage for stage in report["stages"] if stage["stage_key"] == "proposal")
        assert proposal["probability_percent"] is None
        assert proposal["weighted_expected_amount_by_currency"] == {}


        aging = await client.get(
            "/api/v1/crm/opportunities/stage-aging",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "as_of": "2026-12-10",
                "limit": 2,
            },
        )
        assert aging.status_code == 200, aging.text
        aging_report = aging.json()
        assert aging_report["as_of"] == "2026-12-10"
        assert aging_report["total"] == 4
        assert len(aging_report["items"]) == 2
        assert all(item["history_complete"] and item["days_in_stage"] is not None
                   for item in aging_report["items"])
        counts_by_stage = {item["stage_key"]: item["opportunity_count"]
                           for item in aging_report["buckets"]}
        assert counts_by_stage == {"proposal": 1, "qualified": 3}
        assert all(item["unknown_duration_count"] == 0
                   for item in aging_report["buckets"])
        stale_only = await client.get(
            "/api/v1/crm/opportunities/stage-aging",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "as_of": "2026-12-10",
                "minimum_days": 999,
            },
        )
        assert stale_only.status_code == 200, stale_only.text
        assert stale_only.json()["total"] == 0

        today = datetime.now(timezone.utc).date().isoformat()
        outcome_report = await client.get(
            "/api/v1/crm/sales-forecast/outcomes",
            headers=headers,
            params={
                "pipeline_id": pipeline_id,
                "period_start": today,
                "period_end": today,
                "organization_unit_id": str(root_id),
            },
        )
        assert outcome_report.status_code == 200, outcome_report.text
        outcomes = outcome_report.json()
        assert outcomes["basis"] == "recorded_terminal_stage_transition"
        assert outcomes["won_count"] == 1
        assert outcomes["lost_count"] == 1
        assert outcomes["won_amount_by_currency"] == {"USD": "7000"}
        assert outcomes["lost_amount_by_currency"] == {"USD": "3000"}
        assert {bucket["outcome_key"] for bucket in outcomes["buckets"]} == {"won", "lost"}

        invalid_stage = await client.patch(
            f"/api/v1/crm/opportunities/{opportunity_id}",
            headers=headers,
            json={"stage_key": "not-a-stage"},
        )
        assert invalid_stage.status_code == 422

        invalid_money = await client.post(
            "/api/v1/crm/opportunities",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "pipeline_id": pipeline_id,
                "name": "Incomplete amount",
                "stage_key": "qualified",
                "amount": "20",
            },
        )
        assert invalid_money.status_code == 422
