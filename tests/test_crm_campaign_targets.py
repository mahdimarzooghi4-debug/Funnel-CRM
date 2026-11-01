from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_targets import evaluate_net_paid_to_spend_target, router
from funnel_crm.api.v1.crm_campaign_target_analytics import router as target_analytics_router
from funnel_crm.api.v1.crm_marketing_manager_dashboard import (
    _csv_safe_text,
    _dashboard_snapshot_changes,
    router as marketing_manager_dashboard_router,
)
from funnel_crm.api.v1.crm_work_items import router as work_items_router
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingCampaignTargetPlan,
    CRMProductCommerceEvent,
    CRMProfileSegment,
    Role,
    RoleAssignment,
    RolePermission,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def test_net_paid_to_spend_target_subtracts_refunds_and_keeps_currencies_separate() -> None:
    tenant_id, organization_unit_id, campaign_id = uuid4(), uuid4(), uuid4()
    plan = CRMMarketingCampaignTargetPlan(
        id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
        campaign_id=campaign_id, period_start=date(2026, 10, 16), period_end=date(2026, 10, 17),
        min_net_paid_to_spend=Decimal("4.5"), net_paid_to_spend_currency="USD",
    )
    measurement = CRMMarketingCampaignMeasurement(
        id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
        campaign_id=campaign_id, measured_on=date(2026, 10, 16), source_label="test",
        actual_spend_amount=Decimal("20"), actual_spend_currency="USD",
    )
    events = [
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
            campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
            source_event_id=uuid4(), event_type="commerce.order.paid", order_reference="A",
            event_kind="paid", amount=Decimal("100"), currency="USD",
            occurred_at=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
            campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
            source_event_id=uuid4(), event_type="commerce.order.refunded", order_reference="A",
            event_kind="refunded", amount=Decimal("10"), currency="USD",
            occurred_at=datetime(2026, 10, 16, 13, tzinfo=timezone.utc),
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=organization_unit_id,
            campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
            source_event_id=uuid4(), event_type="commerce.order.paid", order_reference="B",
            event_kind="paid", amount=Decimal("1000"), currency="EUR",
            occurred_at=datetime(2026, 10, 16, 14, tzinfo=timezone.utc),
        ),
    ]

    result = evaluate_net_paid_to_spend_target(plan, [measurement], events)

    assert result is not None
    assert result.actual == Decimal("4.500000")
    assert result.status == "met"


def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    identity: AuthenticatedIdentity,
) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    app.include_router(target_analytics_router, prefix="/api/v1")
    app.include_router(marketing_manager_dashboard_router, prefix="/api/v1")
    app.include_router(work_items_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_campaign_targets_upsert_and_evaluation_use_currency_matched_observations(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id, campaign_id, partial_campaign_id, campaign_without_measurements_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=f"Targets audience {uuid4().hex[:8]}",
            criteria={"profile_kinds": ["person"]}, is_active=True,
        ))
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Acquisition", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=partial_campaign_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Partial acquisition", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=campaign_without_measurements_id, tenant_id=tenant_id,
                organization_unit_id=root_id, segment_id=segment_id,
                name="Acquisition follow-up", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 16),
                source_label="analytics", impressions=1000, clicks=50, leads=5, conversions=2,
                actual_spend_amount=Decimal("20"), actual_spend_currency="USD",
                attributed_revenue_amount=Decimal("100"), attributed_revenue_currency="USD",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, measured_on=date(2026, 10, 17),
                source_label="analytics", impressions=500, clicks=25, leads=4, conversions=1,
                actual_spend_amount=Decimal("10"), actual_spend_currency="EUR",
                attributed_revenue_amount=Decimal("40"), attributed_revenue_currency="EUR",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=partial_campaign_id, measured_on=date(2026, 10, 16),
                source_label="analytics", impressions=None, clicks=None, leads=2,
                conversions=None, actual_spend_amount=Decimal("30"), actual_spend_currency="USD",
                attributed_revenue_amount=None, attributed_revenue_currency=None,
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Target manager {uuid4().hex[:8]}")
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
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:record_outcome"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.work_item:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.commerce_event:view"),
        ])
        await context.session.flush()
        for kind, amount, order_ref in (("paid", "100.00", "ORDER-1"), ("refunded", "10.00", "ORDER-1")):
            context.session.add(CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=campaign_id, profile_id=None, source_product="funnel.store",
                source_event_id=uuid4(), event_type=(
                    "commerce.order.paid" if kind == "paid" else "commerce.order.refunded"
                ), order_reference=order_ref, event_kind=kind,
                amount=Decimal(amount), currency="USD",
                occurred_at=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
            ))
        context.session.add(CRMProductCommerceEvent(
            id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
            campaign_id=partial_campaign_id, profile_id=None, source_product="funnel.marketplace",
            source_event_id=uuid4(), event_type="commerce.order.paid", order_reference="ORDER-2",
            event_kind="paid", amount=Decimal("300.00"), currency="USD",
            occurred_at=datetime(2026, 10, 16, 15, tzinfo=timezone.utc),
        ))
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        base = f"/api/v1/crm/campaigns/{campaign_id}/targets"
        payload = {
            "period_start": "2026-10-16",
            "period_end": "2026-10-17",
            "impressions_target": 1200,
            "clicks_target": 80,
            "leads_target": 12,
            "max_spend_amount": "40",
            "max_spend_currency": "USD",
            "max_cpl_amount": "5",
            "cpl_currency": "USD",
            "max_cost_per_conversion_amount": "10",
            "conversion_cost_currency": "USD",
            "min_roas": "4",
            "roas_currency": "USD",
            "min_net_paid_to_spend": "4.5",
            "net_paid_to_spend_currency": "USD",
        }
        saved = await client.put(base, headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        target_id = saved.json()["id"]

        listing = await client.get(base, headers=headers)
        assert listing.status_code == 200, listing.text
        assert len(listing.json()) == 1

        evaluation = await client.get(f"{base}/{target_id}/evaluation", headers=headers)
        assert evaluation.status_code == 200, evaluation.text
        metrics = evaluation.json()["metrics"]
        assert metrics["impressions"]["actual"] == 1500
        assert metrics["impressions"]["status"] == "met"
        assert metrics["impressions"]["period_days"] == 2
        assert metrics["impressions"]["recorded_day_coverage_percent"] == "100.00"
        assert metrics["clicks"]["actual"] == 75
        assert metrics["clicks"]["status"] == "not_met"

        follow_up = await client.post(
            "/api/v1/crm/work-items/from-campaign-signal",
            headers=headers,
            json={
                "campaign_id": str(campaign_id),
                "target_plan_id": target_id,
                "metric_key": "clicks",
                "priority": "high",
                "note": "Review creative and audience performance.",
            },
        )
        assert follow_up.status_code == 201, follow_up.text
        assert follow_up.json()["campaign_id"] == str(campaign_id)
        assert follow_up.json()["title"] == "Review Acquisition: clicks"
        assert "target_gap" in follow_up.json()["description"]
        assert follow_up.json()["source_campaign_target_plan_id"] == target_id
        assert follow_up.json()["source_campaign_metric_key"] == "clicks"
        assert follow_up.json()["source_campaign_signal_type"] == "target_gap"
        duplicate_follow_up = await client.post(
            "/api/v1/crm/work-items/from-campaign-signal",
            headers=headers,
            json={
                "campaign_id": str(campaign_id),
                "target_plan_id": target_id,
                "metric_key": "clicks",
                "priority": "high",
            },
        )
        assert duplicate_follow_up.status_code == 409
        assert duplicate_follow_up.json()["detail"]["work_item_id"] == follow_up.json()["id"]

        outcome_payload = {
            "request_id": str(uuid4()),
            "decision_key": "adjusted",
            "notes": "Refreshed the campaign creative based on the click gap.",
            "occurred_at": "2026-10-18T12:00:00Z",
        }
        outcome = await client.post(
            f"/api/v1/crm/work-items/{follow_up.json()['id']}/campaign-signal-outcomes",
            headers=headers,
            json=outcome_payload,
        )
        assert outcome.status_code == 201, outcome.text
        assert outcome.json()["metric_actual"] == "75"
        assert outcome.json()["metric_status"] == "not_met"
        assert outcome.json()["decision_key"] == "adjusted"
        repeated_outcome = await client.post(
            f"/api/v1/crm/work-items/{follow_up.json()['id']}/campaign-signal-outcomes",
            headers=headers,
            json=outcome_payload,
        )
        assert repeated_outcome.status_code == 200, repeated_outcome.text
        assert repeated_outcome.json()["id"] == outcome.json()["id"]
        outcome_history = await client.get(
            f"/api/v1/crm/work-items/{follow_up.json()['id']}/campaign-signal-outcomes",
            headers=headers,
        )
        assert outcome_history.status_code == 200, outcome_history.text
        assert len(outcome_history.json()) == 1

        outcome_report = await client.get(
            "/api/v1/crm/analytics/campaign-target-performance/follow-up-outcomes",
            headers=headers,
            params={"period_start": "2026-10-18", "period_end": "2026-10-18"},
        )
        assert outcome_report.status_code == 200, outcome_report.text
        report = outcome_report.json()
        assert report["total"] == 1
        assert report["outcomes_by_decision"] == {"adjusted": 1}
        assert report["outcomes_by_metric"] == {"clicks": 1}
        assert report["items"][0]["campaign_name"] == "Acquisition"
        assert report["items"][0]["metric_actual"] == "75"
        assert "do not show that a decision caused" in report["basis"]

        assert metrics["spend"]["actual"] == "20.000000"
        assert metrics["spend"]["observed_days"] == 1
        assert metrics["spend"]["period_days"] == 2
        assert metrics["spend"]["recorded_day_coverage_percent"] == "50.00"
        assert metrics["cost_per_lead"]["actual"] == "4.000000"
        assert metrics["cost_per_lead"]["paired_days"] == 1
        assert metrics["cost_per_conversion"]["actual"] == "10.000000"
        assert metrics["roas"]["actual"] == "5.000000"
        assert metrics["roas"]["status"] == "met"
        assert metrics["period_net_paid_to_spend"]["actual"] == "4.500000"
        assert metrics["period_net_paid_to_spend"]["status"] == "met"

        partial_campaign_target = await client.put(
            f"/api/v1/crm/campaigns/{partial_campaign_id}/targets",
            headers=headers,
            json={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "leads_target": 8,
            },
        )
        assert partial_campaign_target.status_code == 200, partial_campaign_target.text

        campaign_without_measurements_target = await client.put(
            f"/api/v1/crm/campaigns/{campaign_without_measurements_id}/targets",
            headers=headers,
            json={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "leads_target": 10,
            },
        )
        assert campaign_without_measurements_target.status_code == 200, campaign_without_measurements_target.text

        portfolio = await client.get(
            "/api/v1/crm/analytics/campaign-target-performance/portfolio",
            headers=headers,
            params={
                "period_start": "2026-10-16",
                "period_end": "2026-10-17",
                "grouped_by": "channel",
            },
        )
        assert portfolio.status_code == 200, portfolio.text
        report = portfolio.json()
        assert report["campaign_count"] == 3
        assert report["metric_outcomes"]["impressions"] == {
            "evaluated": 1, "met": 1, "not_met": 0, "no_data": 0,
        }
        assert report["metric_outcomes"]["clicks"] == {
            "evaluated": 1, "met": 0, "not_met": 1, "no_data": 0,
        }
        assert any(
            signal["metric_key"] == "clicks" and signal["signal_type"] == "target_gap"
            for signal in report["manager_signals"]
        )
        assert any(
            signal["signal_type"] == "measurement_gap" and signal["observed_days"] < signal["period_days"]
            for signal in report["manager_signals"]
        )
        assert "do not establish causality" in report["manager_signals_basis"]
        assert report["groups"][0]["key"] == "web"
        assert report["metric_variances"]["leads"] == {
            "targeted_campaign_count": 3,
            "complete_campaign_count": 1,
            "incomplete_campaign_count": 2,
            "target_total": 30,
            "complete_actual_total": 9,
            "complete_campaign_target_total": 12,
            "complete_variance": -3,
            "incomplete_target_total": 18,
            "partial_actual_total": 2,
        }
        assert report["groups"][0]["metric_variances"]["leads"]["incomplete_target_total"] == 18
        assert report["campaigns"][0]["metrics"]["roas"]["currency"] == "USD"
        assert report["period_calendar_days"] == 2

        dashboard = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns",
            headers=headers,
            params={"period_start": "2026-10-16", "period_end": "2026-10-17"},
        )
        assert dashboard.status_code == 200, dashboard.text
        dashboard_report = dashboard.json()
        assert dashboard_report["performance"]["campaign_count"] == 3
        assert dashboard_report["performance"]["measured_campaign_count"] == 2
        assert dashboard_report["performance"]["planned_budget_by_currency"] == {}
        assert dashboard_report["performance"]["actual_spend_by_currency"] == {
            "EUR": "10.000000", "USD": "50.000000",
        }
        assert dashboard_report["data_quality"]["campaigns_without_measurements"] == 1
        assert dashboard_report["data_quality"]["expected_campaign_days"] == 6
        assert dashboard_report["data_quality"]["covered_campaign_days"] == 3
        assert dashboard_report["data_quality"]["missing_campaign_days"] == 3
        assert dashboard_report["target_attainment"]["campaign_count"] == 3
        assert dashboard_report["target_attainment"]["metric_outcomes"]["clicks"] == {
            "evaluated": 1, "met": 0, "not_met": 1, "no_data": 0,
        }
        assert len(dashboard_report["channel_performance"]) == 1
        assert len(dashboard_report["segment_performance"]) == 1

        export_response = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/export.csv",
            headers=headers,
            params={"period_start": "2026-10-16", "period_end": "2026-10-17"},
        )
        assert export_response.status_code == 200, export_response.text
        assert export_response.headers["content-type"].startswith("text/csv")
        assert "attachment;" in export_response.headers["content-disposition"]
        export_text = export_response.content.decode("utf-8-sig")
        assert export_text.startswith("record_type,key,label,currency,metric,value")
        assert "report_definition_version" in export_text
        assert "metric_coverage" in export_text
        assert "target_outcome" in export_text
        assert "manager_signal" in export_text

        snapshot_response = await client.post(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshots",
            headers=headers,
            params={"period_start": "2026-10-16", "period_end": "2026-10-17"},
        )
        assert snapshot_response.status_code == 201, snapshot_response.text
        snapshot = snapshot_response.json()
        assert len(snapshot["snapshot_hash"]) == 64
        snapshot_id = snapshot["id"]

        listed_snapshots = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshots",
            headers=headers,
        )
        assert listed_snapshots.status_code == 200, listed_snapshots.text
        assert [item["id"] for item in listed_snapshots.json()["items"]][0] == snapshot_id

        fetched_snapshot = await client.get(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshots/{snapshot_id}",
            headers=headers,
        )
        assert fetched_snapshot.status_code == 200, fetched_snapshot.text
        snapshot_body = fetched_snapshot.json()
        assert snapshot_body["integrity_verified"] is True
        assert snapshot_body["snapshot_hash"] == snapshot["snapshot_hash"]
        assert snapshot_body["dashboard"]["period_start"] == "2026-10-16"

        action_response = await client.post(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshots/{snapshot_id}/actions",
            headers=headers,
            json={
                "title": "Review low campaign coverage",
                "decision_note": "Ask the channel lead to verify missing campaign days.",
                "due_on": "2026-10-20",
            },
        )
        assert action_response.status_code == 201, action_response.text
        action = action_response.json()
        assert action["status"] == "open"
        assert action["due_on"] == "2026-10-20"

        listed_actions = await client.get(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshots/{snapshot_id}/actions",
            headers=headers,
        )
        assert listed_actions.status_code == 200, listed_actions.text
        assert listed_actions.json()["items"][0]["id"] == action["id"]

        closed_action = await client.patch(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action['id']}",
            headers=headers,
            json={"status": "completed", "outcome": "Channel lead confirmed the tracking gap."},
        )
        assert closed_action.status_code == 200, closed_action.text
        assert closed_action.json()["status"] == "completed"
        repeated_close = await client.patch(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action['id']}",
            headers=headers,
            json={"status": "cancelled", "outcome": "No longer needed."},
        )
        assert repeated_close.status_code == 409

        action_worklist = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions",
            headers=headers,
            params={"status": "completed"},
        )
        assert action_worklist.status_code == 200, action_worklist.text
        assert action_worklist.json()["items"][0]["id"] == action["id"]
        assert action_worklist.json()["items"][0]["outcome"] == (
            "Channel lead confirmed the tracking gap."
        )

        overdue_action = await client.post(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshots/{snapshot_id}/actions",
            headers=headers,
            json={
                "title": "Resolve missing daily measurements",
                "decision_note": "Request the missing figures from the campaign operator.",
                "due_on": "2000-01-01",
            },
        )
        assert overdue_action.status_code == 201, overdue_action.text

        deadline_alerts = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/alerts",
            headers=headers,
        )
        assert deadline_alerts.status_code == 200, deadline_alerts.text
        alerts = deadline_alerts.json()
        assert alerts["overdue_count"] == 1
        overdue_item = next(
            item for item in alerts["items"] if item["id"] == overdue_action.json()["id"]
        )
        assert overdue_item["deadline_state"] == "overdue"
        assert overdue_item["days_until_due"] < 0

        action_analytics = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/analytics",
            headers=headers,
        )
        assert action_analytics.status_code == 200, action_analytics.text
        analytics = action_analytics.json()
        assert analytics["total_count"] == 2
        assert analytics["open_count"] == 1
        assert analytics["completed_count"] == 1
        assert analytics["overdue_open_count"] == 1
        assert analytics["completion_rate_percent"] == "100.00"
        assert analytics["average_days_to_close"] is not None

        second_snapshot_response = await client.post(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshots",
            headers=headers,
            params={"period_start": "2026-10-16", "period_end": "2026-10-17"},
        )
        assert second_snapshot_response.status_code == 201, second_snapshot_response.text
        current_snapshot_id = second_snapshot_response.json()["id"]

        verification = await client.post(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action['id']}/verifications",
            headers=headers,
            json={
                "current_snapshot_id": current_snapshot_id,
                "metric_path": "performance.totals.clicks",
                "expected_direction": "unchanged",
            },
        )
        assert verification.status_code == 201, verification.text
        verified = verification.json()
        assert verified["baseline_value"] == verified["current_value"]
        assert verified["absolute_change"] == "0"
        assert verified["direction_matched"] is True
        assert "does not establish" in verified["interpretation"]

        verification_history = await client.get(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action['id']}/verifications",
            headers=headers,
        )
        assert verification_history.status_code == 200, verification_history.text
        assert len(verification_history.json()["items"]) == 1

        learning_analytics = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/verification-analytics",
            headers=headers,
        )
        assert learning_analytics.status_code == 200, learning_analytics.text
        learning_report = learning_analytics.json()
        assert learning_report["summary"]["verification_count"] == 1
        assert learning_report["summary"]["expected_count"] == 1
        assert learning_report["summary"]["matched_count"] == 1
        assert learning_report["summary"]["direction_match_rate_percent"] == "100.00"
        assert learning_report["metrics"][0]["metric_path"] == "performance.totals.clicks"
        assert learning_report["metrics"][0]["unchanged_count"] == 1

        learning_export = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/verification-analytics/export.csv",
            headers=headers,
        )
        assert learning_export.status_code == 200, learning_export.text
        assert learning_export.headers["content-type"].startswith("text/csv")
        learning_csv = learning_export.content.decode("utf-8-sig")
        assert learning_csv.startswith(
            "record_type,metric_path,value,verification_count,expected_count"
        )
        assert "performance.totals.clicks" in learning_csv

        duplicate_verification = await client.post(
            f"/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-actions/{action['id']}/verifications",
            headers=headers,
            json={
                "current_snapshot_id": current_snapshot_id,
                "metric_path": "performance.totals.clicks",
                "expected_direction": "unchanged",
            },
        )
        assert duplicate_verification.status_code == 409

        comparison = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-comparisons",
            headers=headers,
            params={"baseline_id": snapshot_id, "current_id": current_snapshot_id},
        )
        assert comparison.status_code == 200, comparison.text
        assert comparison.json()["change_count"] == 0

        comparison_export = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/snapshot-comparisons/export.csv",
            headers=headers,
            params={"baseline_id": snapshot_id, "current_id": current_snapshot_id},
        )
        assert comparison_export.status_code == 200, comparison_export.text
        assert comparison_export.headers["content-type"].startswith("text/csv")
        assert "attachment;" in comparison_export.headers["content-disposition"]
        comparison_csv = comparison_export.content.decode("utf-8-sig")
        assert comparison_csv.startswith(
            "record_type,path,status,previous,current,absolute_change,percent_change"
        )
        assert "report_definition_version" in comparison_csv
        assert "change_count,," in comparison_csv

        assert report["metric_definitions"]["roas"]["key"] == "reported_roas"
        assert report["metric_outcomes"]["period_net_paid_to_spend"]["met"] == 1
        pooled_usd = next(
            row for row in report["commerce_outcomes_by_currency"] if row["currency"] == "USD"
        )
        assert pooled_usd["campaign_count"] == 2
        assert pooled_usd["spend_amount"] == "50.000000"
        assert pooled_usd["net_paid_amount"] == "390.000000"
        assert pooled_usd["observed_net_paid_to_spend_multiple"] == "7.800000"
        assert report["commerce_basis"].startswith("Only campaign-linked")
        assert report["metric_definitions"]["net_paid_amount"]["key"] == "net_paid_amount"
        group_usd = next(
            row for row in report["groups"][0]["commerce_outcomes_by_currency"]
            if row["currency"] == "USD"
        )
        assert group_usd["campaign_count"] == 2
        assert group_usd["net_paid_amount_per_paid_order"] == "195.000000"
        source_usd = {
            (row["source_product"], row["currency"]): row
            for row in report["commerce_outcomes_by_source_product"]
        }
        assert source_usd[("funnel.store", "USD")]["net_paid_amount"] == "90.000000"
        assert source_usd[("funnel.marketplace", "USD")]["net_paid_amount"] == "300.000000"
        assert source_usd[("funnel.marketplace", "USD")]["net_paid_amount_per_paid_order"] == "300.000000"
        assert report["metric_definitions"]["spend"]["key"] == "actual_spend"
        assert report["campaigns"][0]["metrics"]["spend"]["recorded_day_coverage_percent"] == "50.00"
        assert "missing days are not zero" in report["coverage_basis"]

        comparison = await client.get(
            "/api/v1/crm/analytics/campaign-target-performance/portfolio",
            headers=headers,
            params=[
                ("period_start", "2026-10-16"),
                ("period_end", "2026-10-17"),
                ("campaign_ids", str(campaign_id)),
                ("campaign_ids", str(partial_campaign_id)),
            ],
        )
        assert comparison.status_code == 200, comparison.text
        comparison_report = comparison.json()
        assert comparison_report["campaign_count"] == 2
        assert {item["campaign_id"] for item in comparison_report["campaigns"]} == {
            str(campaign_id), str(partial_campaign_id),
        }
        assert comparison_report["metric_variances"]["leads"]["targeted_campaign_count"] == 2

        duplicate_selection = await client.get(
            "/api/v1/crm/analytics/campaign-target-performance/portfolio",
            headers=headers,
            params=[
                ("period_start", "2026-10-16"),
                ("period_end", "2026-10-17"),
                ("campaign_ids", str(campaign_id)),
                ("campaign_ids", str(campaign_id)),
            ],
        )
        assert duplicate_selection.status_code == 422

        payload["clicks_target"] = 70
        updated = await client.put(base, headers=headers, json=payload)
        assert updated.status_code == 200, updated.text
        assert updated.json()["id"] == target_id
        assert len((await client.get(base, headers=headers)).json()) == 1

        invalid = await client.put(base, headers=headers, json={
            "period_start": "2026-01-01",
            "period_end": "2027-01-02",
            "leads_target": 10,
        })
        assert invalid.status_code == 422

        pacing_campaign_id = uuid4()
        async with tenant_session(
            runtime_session_factory,
            requested_tenant_id=tenant_id,
            identity=identity,
        ) as context:
            context.session.add(CRMMarketingCampaign(
                id=pacing_campaign_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                segment_id=segment_id,
                name="Scheduled budget pacing",
                objective_key="acquisition",
                channel="web",
                planned_budget_amount=Decimal("100"),
                planned_budget_currency="USD",
                starts_at=datetime(2026, 10, 16, 0, tzinfo=timezone.utc),
                ends_at=datetime(2026, 10, 17, 23, 59, tzinfo=timezone.utc),
                status="active",
            ))
            context.session.add(CRMMarketingCampaignMeasurement(
                id=uuid4(),
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                campaign_id=pacing_campaign_id,
                measured_on=date(2026, 10, 16),
                source_label="pacing-test",
                actual_spend_amount=Decimal("20"),
                actual_spend_currency="USD",
            ))
            await context.session.flush()

        pacing_response = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/budget-pacing",
            headers=headers,
            params={"period_start": "2026-10-16", "as_of": "2026-10-16"},
        )
        assert pacing_response.status_code == 200, pacing_response.text
        pacing_report = pacing_response.json()
        pacing_item = next(
            item for item in pacing_report["items"]
            if item["campaign_id"] == str(pacing_campaign_id)
        )
        assert pacing_item["expected_spend_to_date"] == "50"
        assert pacing_item["actual_spend_in_budget_currency"] == "20.000000"
        assert pacing_item["variance_from_expected"] == "-30.000000"
        assert pacing_item["pacing_status"] == "behind_pace"
        assert pacing_item["budget_currency"] == "USD"

        pacing_export = await client.get(
            "/api/v1/crm/analytics/marketing-manager/campaigns/budget-pacing/export.csv",
            headers=headers,
            params={"period_start": "2026-10-16", "as_of": "2026-10-16"},
        )
        assert pacing_export.status_code == 200, pacing_export.text
        assert pacing_export.headers["content-type"].startswith("text/csv")
        assert "attachment;" in pacing_export.headers["content-disposition"]
        pacing_csv = pacing_export.content.decode("utf-8-sig")
        assert pacing_csv.startswith(
            "record_type,campaign_id,campaign_name,currency,pacing_status"
        )
        assert "behind_pace" in pacing_csv
        assert "Scheduled budget pacing" in pacing_csv


def test_dashboard_csv_text_neutralizes_spreadsheet_formulas() -> None:
    assert _csv_safe_text("=HYPERLINK(\"https://example.invalid\")").startswith("'=")
    assert _csv_safe_text("ordinary segment").startswith("ordinary")
    assert _csv_safe_text("  @SUM(A1:A2)").startswith("'  @")



def test_dashboard_snapshot_diff_keeps_missing_distinct_from_zero() -> None:
    changes = _dashboard_snapshot_changes(
        {
            "performance": {
                "totals": {"clicks": 10},
                "actual_spend_by_currency": {"USD": "5.000000", "EUR": "2.000000"},
            }
        },
        {
            "performance": {
                "totals": {"clicks": 15, "leads": 0},
                "actual_spend_by_currency": {"USD": "7.500000"},
            }
        },
    )
    by_path = {item["path"]: item for item in changes}
    assert by_path["performance.totals.clicks"]["absolute_change"] == "5"
    assert by_path["performance.actual_spend_by_currency.USD"]["percent_change"] == "50.0"
    assert by_path["performance.totals.leads"]["status"] == "added"
    assert by_path[
        "performance.actual_spend_by_currency.EUR"
    ]["status"] == "removed"
    assert by_path["performance.actual_spend_by_currency.EUR"]["current"] is None
