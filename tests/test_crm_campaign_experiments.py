import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_campaign_experiments import router
from funnel_crm.api.v1.crm_campaign_experiments import (
    _coverage_classification,
    _metric_coverage,
    _metric_value,
    _spreadsheet_safe,
)
from funnel_crm.platform.models import (
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMProductCommerceEvent,
    CRMProfileSegment,
    Role,
    RoleAssignment,
    RolePermission,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def test_metric_coverage_reports_missing_days_and_qualifying_sources() -> None:
    campaign_id = uuid4()
    rows = [
        CRMMarketingCampaignMeasurement(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(),
            campaign_id=campaign_id, measured_on=date(2026, 10, 16),
            source_label="weekly export", conversions=4,
        ),
        CRMMarketingCampaignMeasurement(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(),
            campaign_id=campaign_id, measured_on=date(2026, 10, 17),
            source_label="click-only export", clicks=8,
        ),
    ]

    expected, missing, coverage, missing_dates, sources = _metric_coverage(
        "conversions", None, rows, date(2026, 10, 16), date(2026, 10, 18)
    )

    assert (expected, missing, coverage) == (3, 2, 33.33)
    assert missing_dates == [date(2026, 10, 17), date(2026, 10, 18)]
    assert sources == ["weekly export"]


@pytest.mark.parametrize(
    ("minimum", "maximum", "completeness", "balance"),
    [
        (100.0, 100.0, "complete", "equal"),
        (0.0, 0.0, "unavailable", "equal"),
        (33.33, 66.67, "partial", "unequal"),
    ],
)
def test_coverage_classification_uses_observed_data_only(
    minimum: float,
    maximum: float,
    completeness: str,
    balance: str,
) -> None:
    assert _coverage_classification(minimum, maximum) == (completeness, balance)


def test_csv_cells_are_safe_for_spreadsheet_import() -> None:
    assert _spreadsheet_safe("=1+1") == "'=1+1"
    assert _spreadsheet_safe("  @SUM(A1:A2)") == "'  @SUM(A1:A2)"
    assert _spreadsheet_safe("campaign name") == "campaign name"
    assert _spreadsheet_safe(Decimal("-33.34")) == Decimal("-33.34")


def test_incentive_cost_metric_uses_only_matching_currency_rows() -> None:
    rows = [
        CRMMarketingCampaignMeasurement(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(),
            campaign_id=uuid4(), measured_on=date(2026, 10, 16),
            source_label="promotion ledger", incentive_cost_amount=Decimal("4.25"),
            incentive_cost_currency="USD",
        ),
        CRMMarketingCampaignMeasurement(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(),
            campaign_id=uuid4(), measured_on=date(2026, 10, 16),
            source_label="other currency ledger", incentive_cost_amount=Decimal("9"),
            incentive_cost_currency="EUR",
        ),
    ]

    value, observed_days, paired_days = _metric_value("incentive_cost", "USD", rows)
    coverage = _metric_coverage(
        "incentive_cost", "USD", rows, date(2026, 10, 16), date(2026, 10, 16)
    )

    assert value == Decimal("4.25")
    assert observed_days == paired_days == 1
    assert coverage == (1, 0, 100.0, [], ["promotion ledger"])


def test_refunded_amount_metric_uses_matching_currency_and_sources() -> None:
    rows = [
        CRMMarketingCampaignMeasurement(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            measured_on=date(2026, 10, 16), source_label="returns ledger",
            refunded_amount=Decimal("12.50"), refunded_currency="USD",
        ),
        CRMMarketingCampaignMeasurement(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            measured_on=date(2026, 10, 16), source_label="other currency",
            refunded_amount=Decimal("30"), refunded_currency="EUR",
        ),
    ]
    assert _metric_value("refunded_amount", "USD", rows) == (Decimal("12.50"), 1, 1)
    assert _metric_coverage(
        "refunded_amount", "USD", rows, date(2026, 10, 16), date(2026, 10, 16)
    ) == (1, 0, 100.0, [], ["returns ledger"])


def test_order_linked_refund_metrics_deduplicate_orders_but_sum_partial_refunds() -> None:
    day = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    events = [
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.refunded",
            order_reference="O-1", event_kind="refunded", amount=Decimal("3"), currency="USD",
            occurred_at=day,
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.refunded.partial",
            order_reference="O-1", event_kind="refunded", amount=Decimal("2"), currency="USD",
            occurred_at=day.replace(hour=13),
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.refunded",
            order_reference="O-2", event_kind="refunded", amount=Decimal("20"), currency="EUR",
            occurred_at=day,
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.refunded",
            order_reference="O-3", event_kind="refunded", amount=Decimal("4"), currency="USD",
            occurred_at=day,
        ),
    ]
    rows: list[CRMMarketingCampaignMeasurement] = []
    assert _metric_value("refunded_order_count", None, rows, events) == (3, 1, 0)
    assert _metric_value("refund_amount", "USD", rows, events) == (Decimal("9"), 1, 0)
    assert _metric_value("average_refund_per_order", "USD", rows, events) == (Decimal("4.500000"), 1, 0)
    assert _metric_coverage(
        "refund_amount", "USD", rows, date(2026, 10, 16), date(2026, 10, 17), events
    ) == (2, 1, 50.0, [date(2026, 10, 17)], ["store"])


def test_refunded_order_rate_matches_unique_paid_orders_and_counts_paid_event_days() -> None:
    day = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    events = [
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.paid",
            order_reference="O-1", event_kind="paid", amount=Decimal("20"), currency="USD", occurred_at=day,
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.paid.partial",
            order_reference="O-1", event_kind="paid", amount=Decimal("20"), currency="USD", occurred_at=day,
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.refunded",
            order_reference="O-1", event_kind="refunded", amount=Decimal("5"), currency="USD", occurred_at=day,
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.paid",
            order_reference="O-2", event_kind="paid", amount=Decimal("30"), currency="USD", occurred_at=day,
        ),
        CRMProductCommerceEvent(
            id=uuid4(), tenant_id=uuid4(), organization_unit_id=uuid4(), campaign_id=uuid4(),
            source_product="store", source_event_id=uuid4(), event_type="order.refunded",
            order_reference="O-3", event_kind="refunded", amount=Decimal("4"), currency="USD", occurred_at=day,
        ),
    ]
    assert _metric_value("paid_order_count", None, [], events) == (2, 1, 0)
    assert _metric_value("paid_amount", "USD", [], events) == (Decimal("70"), 1, 0)
    assert _metric_value("average_paid_order_value", "USD", [], events) == (Decimal("35.000000"), 1, 0)
    assert _metric_value("refunded_order_rate_percent", None, [], events) == (Decimal("50.0000"), 1, 0)
    assert _metric_coverage(
        "refunded_order_rate_percent", None, [], date(2026, 10, 16), date(2026, 10, 17), events
    ) == (2, 1, 50.0, [date(2026, 10, 17)], ["store"])


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
    return app


@pytest.mark.asyncio
async def test_campaign_experiment_readout_compares_variants_descriptively(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    segment_id = uuid4()
    control_id, variant_id = uuid4(), uuid4()
    segment_name = f"Experiment audience {uuid4().hex[:8]}"
    segment_criteria = {"profile_kinds": ["person"]}
    experiment_id: UUID
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add(CRMProfileSegment(
            id=segment_id, tenant_id=tenant_id, organization_unit_id=root_id,
            name=segment_name,
            criteria=segment_criteria, is_active=True,
        ))
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaign(
                id=control_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Control campaign", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
            CRMMarketingCampaign(
                id=variant_id, tenant_id=tenant_id, organization_unit_id=root_id,
                segment_id=segment_id, name="Variant campaign", objective_key="acquisition",
                channel="web", planned_budget_amount=None, planned_budget_currency=None,
                starts_at=None, ends_at=None, status="draft",
            ),
        ])
        await context.session.flush()
        context.session.add_all([
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=control_id, measured_on=date(2026, 10, 16),
                source_label="control report", impressions=1000, clicks=100,
                leads=40, conversions=10, assigned_count=100, exposure_count=80,
                incentive_cost_amount=Decimal("20"), incentive_cost_currency="USD",
                return_count=2, refunded_amount=Decimal("30"), refunded_currency="USD",
                actual_spend_amount=Decimal("100"), actual_spend_currency="USD",
                attributed_revenue_amount=Decimal("300"), attributed_revenue_currency="USD",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=variant_id, measured_on=date(2026, 10, 16),
                source_label="variant report", impressions=1000, clicks=120,
                leads=50, conversions=15, assigned_count=100, exposure_count=90,
                incentive_cost_amount=Decimal("10"), incentive_cost_currency="USD",
                return_count=1, refunded_amount=Decimal("12"), refunded_currency="USD",
                actual_spend_amount=Decimal("90"), actual_spend_currency="USD",
                attributed_revenue_amount=Decimal("360"), attributed_revenue_currency="USD",
            ),
            CRMMarketingCampaignMeasurement(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=control_id, measured_on=date(2026, 10, 17),
                source_label="control report", conversions=0,
                assigned_count=25, exposure_count=20,
            ),
        ])
        context.session.add_all([
            CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=control_id, source_product="funnel.store", source_event_id=uuid4(),
                event_type="commerce.order.refund", order_reference="CONTROL-1",
                event_kind="refunded", amount=Decimal("3"), currency="USD",
                occurred_at=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
            ),
            CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=control_id, source_product="funnel.store", source_event_id=uuid4(),
                event_type="commerce.order.refund.partial", order_reference="CONTROL-1",
                event_kind="refunded", amount=Decimal("2"), currency="USD",
                occurred_at=datetime(2026, 10, 16, 13, tzinfo=timezone.utc),
            ),
            CRMProductCommerceEvent(
                id=uuid4(), tenant_id=tenant_id, organization_unit_id=root_id,
                campaign_id=variant_id, source_product="funnel.store", source_event_id=uuid4(),
                event_type="commerce.order.refund", order_reference="VARIANT-1",
                event_kind="refunded", amount=Decimal("4"), currency="USD",
                occurred_at=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Experiment manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id, membership_id=context.access.membership_id,
                role_id=role.id, organization_unit_id=root_id,
            ),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:view"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.campaign:manage"),
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key="crm.commerce_event:view"),
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "organization_unit_id": str(root_id),
            "name": "Landing page headline test",
            "hypothesis": "Variant headline may increase completed conversions.",
            "allocation_method": "Random assignment by eligible customer ID in the execution platform.",
            "known_limitations": "Possible cross-channel exposure is not captured.",
            "primary_metric": "conversions",
            "guardrails": [
                {"metric": "clicks"}, {"metric": "roas", "currency": "USD"},
                {"metric": "incentive_cost", "currency": "USD"},
                {"metric": "refunded_amount", "currency": "USD"},
                {"metric": "refunded_order_count"},
                {"metric": "refund_amount", "currency": "USD"},
            ],
            "period_start": "2026-10-16",
            "period_end": "2026-10-18",
            "variants": [
                {"campaign_id": str(control_id), "label": "Existing headline", "is_control": True},
                {"campaign_id": str(variant_id), "label": "New headline", "is_control": False},
            ],
        }
        created = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=payload
        )
        assert created.status_code == 201, created.text
        experiment_id = UUID(created.json()["id"])

        listed = await client.get("/api/v1/crm/campaign-experiments", headers=headers)
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1
        assert listed.json()[0]["experiment"]["id"] == str(experiment_id)
        assert listed.json()[0]["experiment"]["guardrail_metrics"] == [
            {"metric": "clicks", "currency": None},
            {"metric": "roas", "currency": "USD"},
            {"metric": "incentive_cost", "currency": "USD"},
            {"metric": "refunded_amount", "currency": "USD"},
            {"metric": "refunded_order_count", "currency": None},
            {"metric": "refund_amount", "currency": "USD"},
        ]
        assert listed.json()[0]["experiment"]["allocation_method"] == payload["allocation_method"]
        assert listed.json()[0]["experiment"]["known_limitations"] == payload["known_limitations"]
        assert listed.json()[0]["experiment"]["audience_snapshot"] == {
            "segment_id": str(segment_id), "segment_name": segment_name,
            "criteria": segment_criteria,
        }

        readout = await client.get(
            f"/api/v1/crm/campaign-experiments/{experiment_id}/readout",
            headers=headers,
        )
        assert readout.status_code == 200, readout.text
        result = readout.json()
        assert result["readout_kind"] == "descriptive_observation"
        primary_coverage = result["coverage_summary"][0]
        assert primary_coverage == {
            "metric": "conversions", "currency": None,
            "variant_count": 2, "variants_with_missing_days": 2,
            "minimum_coverage_percent": 33.33,
            "maximum_coverage_percent": 66.67,
            "coverage_spread_percentage_points": 33.34,
            "completeness": "partial", "coverage_balance": "unequal",
            "variants": [
                {
                    "campaign_id": str(control_id), "label": "Existing headline",
                    "is_control": True, "coverage_percent": 66.67,
                    "expected_days": 3, "missing_days": 1,
                    "missing_dates": ["2026-10-18"],
                    "source_labels": ["control report"],
                },
                {
                    "campaign_id": str(variant_id), "label": "New headline",
                    "is_control": False, "coverage_percent": 33.33,
                    "expected_days": 3, "missing_days": 2,
                    "missing_dates": ["2026-10-17", "2026-10-18"],
                    "source_labels": ["variant report"],
                },
            ],
        }
        clicks_coverage = result["coverage_summary"][1]
        assert clicks_coverage["completeness"] == "partial"
        assert clicks_coverage["coverage_balance"] == "equal"
        assert result["experiment"]["allocation_method"] == payload["allocation_method"]
        assert result["experiment"]["known_limitations"] == payload["known_limitations"]
        assert result["experiment"]["audience_snapshot"]["criteria"] == segment_criteria

        incentive_primary_payload = dict(payload)
        incentive_primary_payload.update({
            "name": "Promotion cost review",
            "primary_metric": "incentive_cost",
            "currency": "USD",
            "guardrails": [{"metric": "clicks"}],
        })
        incentive_primary = await client.post(
            "/api/v1/crm/campaign-experiments",
            headers=headers,
            json=incentive_primary_payload,
        )
        assert incentive_primary.status_code == 201, incentive_primary.text
        incentive_readout = await client.get(
            f"/api/v1/crm/campaign-experiments/{incentive_primary.json()['id']}/readout",
            headers=headers,
        )
        assert incentive_readout.status_code == 200, incentive_readout.text
        assert [Decimal(item["value"]) for item in incentive_readout.json()["variants"]] == [
            Decimal("20"), Decimal("10"),
        ]

        for metric, currency, expected_values in (
            ("refund_amount", "USD", [Decimal("5"), Decimal("4")]),
            ("refunded_order_count", None, [1, 1]),
        ):
            source_refund_payload = dict(payload)
            source_refund_payload.update({
                "name": f"Source refund review: {metric}",
                "primary_metric": metric,
                "guardrails": [{"metric": "clicks"}],
            })
            if currency is None:
                source_refund_payload.pop("currency", None)
            else:
                source_refund_payload["currency"] = currency
            source_refund = await client.post(
                "/api/v1/crm/campaign-experiments",
                headers=headers,
                json=source_refund_payload,
            )
            assert source_refund.status_code == 201, source_refund.text
            source_refund_readout = await client.get(
                f"/api/v1/crm/campaign-experiments/{source_refund.json()['id']}/readout",
                headers=headers,
            )
            assert source_refund_readout.status_code == 200, source_refund_readout.text
            observed = [item["value"] for item in source_refund_readout.json()["variants"]]
            if currency is None:
                assert observed == expected_values
            else:
                assert [Decimal(value) for value in observed] == expected_values

        csv_response = await client.get(
            f"/api/v1/crm/campaign-experiments/{experiment_id}/readout.csv",
            headers=headers,
        )
        assert csv_response.status_code == 200, csv_response.text
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert "attachment; filename=\"campaign-experiment-" in csv_response.headers["content-disposition"]
        csv_rows = list(csv.DictReader(io.StringIO(csv_response.text.lstrip("\ufeff"))))
        assert len(csv_rows) == 18
        variant_csv = next(
            row for row in csv_rows
            if row["variant_campaign_id"] == str(variant_id) and row["metric_role"] == "primary"
        )
        assert variant_csv["missing_dates"] == '["2026-10-17", "2026-10-18"]'
        assert variant_csv["source_labels"] == '["variant report"]'
        assert variant_csv["coverage_delta_vs_control_percentage_points"] == "-33.34"
        variant_assignment_csv = next(
            row for row in csv_rows
            if row["variant_campaign_id"] == str(variant_id)
            and row["metric_role"] == "assignment"
        )
        assert variant_assignment_csv["value"] == "100"
        assert variant_assignment_csv["coverage_percent"] == "33.33"
        variant_incentive_csv = next(
            row for row in csv_rows
            if row["variant_campaign_id"] == str(variant_id)
            and row["metric"] == "incentive_cost"
        )
        assert variant_incentive_csv["value"] == "10.000000"
        assert variant_incentive_csv["currency"] == "USD"
        variant_refund_csv = next(row for row in csv_rows if row["variant_campaign_id"] == str(variant_id) and row["metric"] == "refunded_amount")
        assert variant_refund_csv["value"] == "12.000000"
        variant_source_refund = next(row for row in csv_rows if row["variant_campaign_id"] == str(variant_id) and row["metric"] == "refund_amount")
        assert variant_source_refund["value"] == "4.000000"
        control, variant = result["variants"]
        assert control["is_control"] is True
        assert control["guardrails"][0]["value"] == 100
        assert Decimal(control["guardrails"][1]["value"]) == Decimal("3")
        assert Decimal(control["guardrails"][2]["value"]) == Decimal("20")
        assert Decimal(control["guardrails"][3]["value"]) == Decimal("30")
        assert control["guardrails"][4]["value"] == 1
        assert control["guardrails"][4]["coverage_percent"] == 33.33
        assert control["guardrails"][4]["source_labels"] == ["funnel.store"]
        assert Decimal(control["guardrails"][5]["value"]) == Decimal("5")
        assert control["value"] == 10
        assert control["delta_vs_control"] == 0
        assert control["coverage_percent"] == 66.67
        assert control["coverage_delta_vs_control_percentage_points"] == 0.0
        assert control["assignment"]["count"] == 125
        assert control["assignment"]["coverage_percent"] == 66.67
        assert control["assignment"]["missing_dates"] == ["2026-10-18"]
        assert control["exposure"]["count"] == 100
        assert variant["value"] == 15
        assert variant["delta_vs_control"] == 5
        assert variant["percent_change_vs_control"] == 50.0
        assert variant["observed_days"] == 1
        assert variant["expected_days"] == 3
        assert variant["missing_days"] == 2
        assert variant["coverage_percent"] == 33.33
        assert variant["coverage_delta_vs_control_percentage_points"] == -33.34
        assert variant["assignment"]["count"] == 100
        assert variant["assignment"]["coverage_percent"] == 33.33
        assert variant["assignment"]["missing_dates"] == ["2026-10-17", "2026-10-18"]
        assert variant["exposure"]["count"] == 90
        assert variant["missing_dates"] == ["2026-10-17", "2026-10-18"]
        assert variant["source_labels"] == ["variant report"]
        assert variant["guardrails"][0]["value"] == 120
        assert variant["guardrails"][0]["delta_vs_control"] == 20
        assert variant["guardrails"][0]["percent_change_vs_control"] == 20.0
        assert variant["guardrails"][0]["coverage_percent"] == 33.33
        assert variant["guardrails"][0]["coverage_delta_vs_control_percentage_points"] == 0.0
        assert variant["guardrails"][0]["missing_days"] == 2
        assert variant["guardrails"][0]["source_labels"] == ["variant report"]
        assert Decimal(variant["guardrails"][1]["value"]) == Decimal("4")
        assert Decimal(variant["guardrails"][1]["delta_vs_control"]) == Decimal("1")
        assert variant["guardrails"][1]["status"] == "available"
        assert Decimal(variant["guardrails"][2]["value"]) == Decimal("10")
        assert Decimal(variant["guardrails"][2]["delta_vs_control"]) == Decimal("-10")
        assert Decimal(variant["guardrails"][3]["delta_vs_control"]) == Decimal("-18")
        assert variant["guardrails"][4]["value"] == 1
        assert variant["guardrails"][4]["coverage_percent"] == 33.33
        assert variant["guardrails"][4]["source_labels"] == ["funnel.store"]
        assert Decimal(variant["guardrails"][5]["delta_vs_control"]) == Decimal("-1")

        missing_currency = dict(payload)
        missing_currency["primary_metric"] = "cost_per_conversion"
        invalid = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=missing_currency
        )
        assert invalid.status_code == 422

        missing_incentive_currency = dict(payload)
        missing_incentive_currency["primary_metric"] = "incentive_cost"
        invalid_incentive_design = await client.post(
            "/api/v1/crm/campaign-experiments",
            headers=headers,
            json=missing_incentive_currency,
        )
        assert invalid_incentive_design.status_code == 422

        missing_control = dict(payload)
        missing_control["variants"] = [
            {"campaign_id": str(control_id), "label": "A", "is_control": False},
            {"campaign_id": str(variant_id), "label": "B", "is_control": False},
        ]
        invalid_control = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=missing_control
        )
        assert invalid_control.status_code == 422

        duplicate_guardrail = dict(payload)
        duplicate_guardrail["guardrails"] = [{"metric": "clicks"}, {"metric": "clicks"}]
        invalid_guardrail = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=duplicate_guardrail
        )
        assert invalid_guardrail.status_code == 422

        missing_allocation = dict(payload)
        missing_allocation.pop("allocation_method")
        invalid_design = await client.post(
            "/api/v1/crm/campaign-experiments", headers=headers, json=missing_allocation
        )
        assert invalid_design.status_code == 422
