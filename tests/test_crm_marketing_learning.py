from datetime import date
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_marketing_learning import router
from funnel_crm.api.v1.crm_work_items import router as work_items_router
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMWorkItem,
    CRMProfileSegment,
    Role,
    RoleAssignment,
    RolePermission,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory: async_sessionmaker[AsyncSession], identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    app.include_router(work_items_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_marketing_learning_review_connects_targets_action_and_measured_follow_up(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id, campaign_id = uuid4(), uuid4()
    baseline_id, follow_up_id, empty_follow_up_id = uuid4(), uuid4(), uuid4()
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Learning audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        await context.session.flush()
        context.session.add(CRMMarketingCampaign(
            id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
            segment_id=segment_id, name="Learning campaign", objective_key="acquisition",
            channel="web", planned_budget_amount=None, planned_budget_currency=None,
            starts_at=None, ends_at=None, status="draft",
        ))
        await context.session.flush()

        def target(plan_id, start, end):
            return CRMMarketingCampaignTargetPlan(
                id=plan_id, tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, period_start=start, period_end=end,
                conversions_target=2,
            )

        context.session.add_all([
            target(baseline_id, date(2026, 10, 16), date(2026, 10, 17)),
            target(follow_up_id, date(2026, 10, 18), date(2026, 10, 19)),
            target(empty_follow_up_id, date(2026, 10, 20), date(2026, 10, 21)),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 16),
                source_label="analytics", conversions=1,
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 19),
                source_label="analytics", conversions=3,
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Learning manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:manage"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:create"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:update"),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        base = "/api/v1/crm/marketing-learning/reviews"
        created = await client.post(base, headers=headers, json={
            "campaign_id": str(campaign_id),
            "target_plan_id": str(baseline_id),
            "assessment": "The campaign missed its conversion target in the measured period.",
            "corrective_action": "Revise the landing page and monitor the next period.",
        })
        assert created.status_code == 201, created.text
        review_id = created.json()["id"]
        assert created.json()["status"] == "planned"
        assert created.json()["lesson_learned"] is None

        task_response = await client.post(
            f"{base}/{review_id}/work-item", headers=headers,
            json={"priority": "high", "due_at": "2026-10-28T12:00:00Z"},
        )
        assert task_response.status_code == 200, task_response.text
        task_body = task_response.json()
        assert task_body["created"] is True
        task_id = task_body["work_item"]["id"]
        assert task_body["work_item"]["source_learning_review_id"] == review_id
        assert task_body["work_item"]["campaign_id"] == str(campaign_id)
        assert task_body["work_item"]["priority"] == "high"
        assert "Revise the landing page" in task_body["work_item"]["description"]
        duplicate_task = await client.post(
            f"{base}/{review_id}/work-item", headers=headers, json={},
        )
        assert duplicate_task.status_code == 200, duplicate_task.text
        assert duplicate_task.json()["created"] is False
        assert duplicate_task.json()["work_item"]["id"] == task_id
        task_list = await client.get(
            "/api/v1/crm/work-items", headers=headers,
            params={"organization_unit_id": str(root_id)},
        )
        assert task_list.status_code == 200, task_list.text
        assert [row["id"] for row in task_list.json()] == [task_id]
        task_progress = await client.patch(
            f"/api/v1/crm/work-items/{task_id}", headers=headers,
            json={"status": "in_progress", "due_at": "2026-10-20T09:00:00+03:30"},
        )
        assert task_progress.status_code == 200, task_progress.text

        initial = await client.get(f"{base}/{review_id}", headers=headers)
        assert initial.status_code == 200, initial.text
        assert initial.json()["baseline"]["metrics"]["conversions"]["actual"] == 1
        assert initial.json()["baseline"]["metrics"]["conversions"]["status"] == "not_met"
        assert initial.json()["follow_up"] is None

        portfolio = await client.get(
            f"{base}/portfolio",
            headers=headers,
            params={"period_start": "2026-10-16", "period_end": "2026-10-17",
                    "organization_unit_id": str(root_id),
                    "include_work_items": "true"},
        )
        assert portfolio.status_code == 200, portfolio.text
        portfolio_body = portfolio.json()
        assert portfolio_body["total_count"] == 1
        assert portfolio_body["offset"] == 0
        assert portfolio_body["limit"] == 50
        assert portfolio_body["planned_count"] == 1
        assert portfolio_body["evaluated_count"] == 0
        assert portfolio_body["items"][0]["review"]["id"] == review_id
        assert portfolio_body["items"][0]["learning_state"] == "awaiting_follow_up"
        assert portfolio_body["items"][0]["work_item"]["status"] == "in_progress"
        assert portfolio_body["work_item_counts"] == {
            "linked": 1, "without_work_item": 0, "open": 0,
            "in_progress": 1, "completed": 0, "cancelled": 0, "overdue": 1,
        }
        assert portfolio_body["can_update_work_items"] is True
        assert portfolio_body["can_manage_marketing_reviews"] is True
        empty_page = await client.get(
            f"{base}/portfolio", headers=headers,
            params={"period_start": "2026-10-16", "period_end": "2026-10-17",
                    "organization_unit_id": str(root_id), "limit": 1, "offset": 1},
        )
        assert empty_page.status_code == 200, empty_page.text
        assert empty_page.json()["items"] == []
        assert empty_page.json()["offset"] == 1
        assert empty_page.json()["limit"] == 1
        assert empty_page.json()["has_more"] is False
        overdue_portfolio = await client.get(
            f"{base}/portfolio", headers=headers,
            params={"period_start": "2026-10-16", "period_end": "2026-10-17",
                    "include_work_items": "true", "overdue_only": "true"},
        )
        assert overdue_portfolio.status_code == 200, overdue_portfolio.text
        assert overdue_portfolio.json()["total_count"] == 1
        assert overdue_portfolio.json()["items"][0]["work_item"]["status"] == "in_progress"
        missing_work_item_scope = await client.get(
            f"{base}/portfolio", headers=headers,
            params={"overdue_only": "true"},
        )
        assert missing_work_item_scope.status_code == 422

        missing_data = await client.patch(f"{base}/{review_id}/evaluation", headers=headers, json={
            "follow_up_target_plan_id": str(empty_follow_up_id),
            "follow_up_effectiveness": "We expect improvement after the change.",
            "lesson_learned": "Landing page changes need follow-up measurement.",
        })
        assert missing_data.status_code == 422
        assert "observed target data" in missing_data.text

        evaluated = await client.patch(f"{base}/{review_id}/evaluation", headers=headers, json={
            "follow_up_target_plan_id": str(follow_up_id),
            "follow_up_effectiveness": "Conversions improved in observed follow-up data.",
            "lesson_learned": "The revised page is associated with a higher observed conversion count.",
        })
        assert evaluated.status_code == 200, evaluated.text
        body = evaluated.json()
        assert body["review"]["status"] == "evaluated"
        assert body["review"]["corrective_action"].startswith("Revise")
        assert body["baseline"]["metrics"]["conversions"]["actual"] == 1
        assert body["follow_up"]["metrics"]["conversions"]["actual"] == 3
        assert body["follow_up"]["metrics"]["conversions"]["status"] == "met"
        task_complete = await client.patch(
            f"/api/v1/crm/work-items/{task_id}", headers=headers,
            json={"status": "completed"},
        )
        assert task_complete.status_code == 200, task_complete.text

        evaluated_portfolio = await client.get(
            f"{base}/portfolio",
            headers=headers,
            params={"status": "evaluated", "organization_unit_id": str(root_id),
                    "include_work_items": "true"},
        )
        assert evaluated_portfolio.status_code == 200, evaluated_portfolio.text
        evaluated_body = evaluated_portfolio.json()
        assert evaluated_body["total_count"] == 1
        assert evaluated_body["planned_count"] == 0
        assert evaluated_body["evaluated_count"] == 1
        assert evaluated_body["items"][0]["learning_state"] == "follow_up_evaluated"
        assert evaluated_body["items"][0]["follow_up_period_start"] == "2026-10-18"
        assert evaluated_body["items"][0]["work_item"]["status"] == "completed"
        assert evaluated_body["work_item_counts"]["completed"] == 1
        assert evaluated_body["work_item_counts"]["overdue"] == 0
        lesson_search = await client.get(
            f"{base}/portfolio", headers=headers,
            params={"organization_unit_id": str(root_id),
                    "lesson_query": " observed CONVERSION ", "include_work_items": "true"},
        )
        assert lesson_search.status_code == 200, lesson_search.text
        assert lesson_search.json()["lesson_query"] == "observed CONVERSION"
        assert lesson_search.json()["total_count"] == 1
        assert lesson_search.json()["items"][0]["review"]["id"] == review_id
        literal_wildcard_search = await client.get(
            f"{base}/portfolio", headers=headers,
            params={"lesson_query": "%"},
        )
        assert literal_wildcard_search.status_code == 200, literal_wildcard_search.text
        assert literal_wildcard_search.json()["total_count"] == 0
        completed_overdue_filter = await client.get(
            f"{base}/portfolio", headers=headers,
            params={"include_work_items": "true", "overdue_only": "true"},
        )
        assert completed_overdue_filter.status_code == 200, completed_overdue_filter.text
        assert completed_overdue_filter.json()["total_count"] == 0

        repeated = await client.patch(f"{base}/{review_id}/evaluation", headers=headers, json={
            "follow_up_target_plan_id": str(follow_up_id),
            "follow_up_effectiveness": "Updated note.",
            "lesson_learned": "Updated lesson.",
        })
        assert repeated.status_code == 409

        listed = await client.get(base, headers=headers, params={"campaign_id": str(campaign_id)})
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == review_id

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        events = (await context.session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.target_type.in_([
                    "crm_marketing_learning_review",
                    "crm_marketing_learning_portfolio",
                        "crm_work_item",
                ]),
            )
        )).all()
        assert {event.action_key for event in events} >= {
            "crm_marketing_learning_review.created",
            "crm_marketing_learning_review.viewed",
            "crm_marketing_learning_review.evaluated",
            "crm_marketing_learning.portfolio_viewed",
            "crm_work_item.created_from_marketing_learning_review",
        }
        tasks = (await context.session.scalars(select(CRMWorkItem).where(
            CRMWorkItem.tenant_id == tenant_id,
            CRMWorkItem.source_learning_review_id == UUID(review_id),
        ))).all()
        assert len(tasks) == 1


@pytest.mark.asyncio
async def test_marketing_learning_review_requires_campaign_scope(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)
    app = make_app(runtime_session_factory, identity)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/crm/marketing-learning/reviews",
            headers={"X-Workspace-ID": str(tenant_id)},
            json={
                "campaign_id": str(uuid4()),
                "target_plan_id": str(uuid4()),
                "assessment": "Assessment",
                "corrective_action": "Action",
            },
        )
    assert response.status_code == 404
