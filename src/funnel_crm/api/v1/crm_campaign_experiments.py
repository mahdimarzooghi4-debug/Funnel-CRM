"""Plan and describe campaign variant experiments without claiming causality."""

import csv
import io
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.platform.crm_authorization import crm_scope_ids, has_crm_permission
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignExperiment,
    CRMMarketingCampaignExperimentVariant,
    CRMMarketingCampaignMeasurement,
    CRMProductCommerceEvent,
    CRMProfileSegment,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/campaign-experiments", tags=["CRM marketing experiments"])
ExperimentMetric = Literal[
    "impressions", "clicks", "leads", "conversions", "return_count", "paid_order_count", "refunded_order_count",
    "refunded_order_rate_percent", "matched_refund_order_rate_percent", "matched_paid_refund_order_count", "paid_order_refund_match_rate_percent", "unmatched_refund_order_count",
    "paid_order_without_refund_count",
    "click_through_rate_percent", "conversion_rate_per_click_percent",
    "cost_per_lead", "cost_per_conversion", "roas", "net_paid_to_spend", "incentive_cost", "paid_amount", "net_paid_amount", "net_paid_amount_per_paid_order", "average_paid_order_value", "average_refund_per_order", "refund_to_paid_amount_percent", "refunded_amount", "refund_amount",
]
COUNT_METRICS = {"impressions", "clicks", "leads", "conversions", "return_count"}
CURRENCY_METRICS = {"cost_per_lead", "cost_per_conversion", "roas", "net_paid_to_spend", "incentive_cost", "paid_amount", "net_paid_amount", "net_paid_amount_per_paid_order", "average_paid_order_value", "average_refund_per_order", "refund_to_paid_amount_percent", "refunded_amount", "refund_amount"}
COMMERCE_METRICS = {"paid_order_count", "paid_amount", "net_paid_amount", "net_paid_amount_per_paid_order", "net_paid_to_spend", "average_paid_order_value", "average_refund_per_order", "refund_to_paid_amount_percent", "refunded_order_count", "refunded_order_rate_percent", "matched_refund_order_rate_percent", "matched_paid_refund_order_count", "paid_order_refund_match_rate_percent", "unmatched_refund_order_count", "paid_order_without_refund_count", "refund_amount"}


class ExperimentVariantWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    label: str = Field(min_length=1, max_length=80)
    is_control: bool = False

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("label must contain a non-whitespace character")
        return value


class GuardrailMetricWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: ExperimentMetric
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def validate_currency(self):
        if (self.metric in CURRENCY_METRICS) != (self.currency is not None):
            raise ValueError("currency is required only for currency-based metrics")
        return self


class CampaignExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_unit_id: UUID
    name: str = Field(min_length=1, max_length=160)
    hypothesis: str = Field(min_length=1, max_length=1000)
    primary_metric: ExperimentMetric
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    period_start: date
    period_end: date
    variants: list[ExperimentVariantWrite] = Field(min_length=2, max_length=6)
    guardrails: list[GuardrailMetricWrite] = Field(default_factory=list, max_length=8)
    allocation_method: str = Field(min_length=1, max_length=250)
    known_limitations: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "hypothesis", "allocation_method")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must contain a non-whitespace character")
        return value

    @field_validator("known_limitations")
    @classmethod
    def normalize_limitations(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("known limitations must be omitted or contain text")
        return value

    @model_validator(mode="after")
    def validate_experiment(self) -> "CampaignExperimentCreate":
        if self.period_start > self.period_end or (self.period_end - self.period_start).days >= 366:
            raise ValueError("period must be ordered and no longer than 366 days")
        if (self.primary_metric in CURRENCY_METRICS) != (self.currency is not None):
            raise ValueError("currency is required only for currency-based metrics")
        if len({variant.campaign_id for variant in self.variants}) != len(self.variants):
            raise ValueError("each variant must use a different campaign")
        if sum(variant.is_control for variant in self.variants) != 1:
            raise ValueError("exactly one control variant is required")
        guardrail_keys = [(item.metric, item.currency) for item in self.guardrails]
        if len(set(guardrail_keys)) != len(guardrail_keys):
            raise ValueError("guardrail metrics must be unique")
        if (self.primary_metric, self.currency) in set(guardrail_keys):
            raise ValueError("primary metric cannot also be a guardrail")
        return self


class CampaignExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_unit_id: UUID
    name: str
    hypothesis: str
    primary_metric: str
    currency: str | None
    guardrail_metrics: list[dict[str, str | None]]
    allocation_method: str
    known_limitations: str | None
    audience_snapshot: dict[str, Any] | None
    period_start: date
    period_end: date
    created_at: datetime


class ExperimentVariantRead(BaseModel):
    campaign_id: UUID
    campaign_name: str
    label: str
    is_control: bool


class CampaignExperimentListItem(BaseModel):
    experiment: CampaignExperimentRead
    variants: list[ExperimentVariantRead]


class GuardrailMetricReadout(BaseModel):
    metric: ExperimentMetric
    currency: str | None
    value: int | Decimal | None
    delta_vs_control: int | Decimal | None
    percent_change_vs_control: float | None
    status: Literal["available", "no_data"]
    observed_days: int
    paired_days: int
    expected_days: int
    missing_days: int
    coverage_percent: float
    coverage_delta_vs_control_percentage_points: float | None
    missing_dates: list[date]
    source_labels: list[str]


class DeliveryCountReadout(BaseModel):
    count: int | None
    status: Literal["available", "no_data"]
    observed_days: int
    expected_days: int
    missing_days: int
    coverage_percent: float
    missing_dates: list[date]
    source_labels: list[str]


class VariantReadout(BaseModel):
    campaign_id: UUID
    campaign_name: str
    label: str
    is_control: bool
    value: int | Decimal | None
    delta_vs_control: int | Decimal | None
    percent_change_vs_control: float | None
    currency: str | None
    status: Literal["available", "no_data"]
    observed_days: int
    paired_days: int
    expected_days: int
    missing_days: int
    coverage_percent: float
    coverage_delta_vs_control_percentage_points: float | None
    missing_dates: list[date]
    source_labels: list[str]
    assignment: DeliveryCountReadout
    exposure: DeliveryCountReadout
    metric_per_assigned: Decimal | None = None
    metric_per_exposed: Decimal | None = None
    metric_per_assigned_delta_vs_control: Decimal | None = None
    metric_per_exposed_delta_vs_control: Decimal | None = None
    guardrails: list[GuardrailMetricReadout] = Field(default_factory=list)


class VariantCoverageDetail(BaseModel):
    campaign_id: UUID
    label: str
    is_control: bool
    coverage_percent: float
    expected_days: int
    missing_days: int
    missing_dates: list[date]
    source_labels: list[str]


class CoverageMetricSummary(BaseModel):
    metric: ExperimentMetric
    currency: str | None
    variant_count: int
    variants_with_missing_days: int
    minimum_coverage_percent: float
    maximum_coverage_percent: float
    coverage_spread_percentage_points: float
    completeness: Literal["complete", "partial", "unavailable"]
    coverage_balance: Literal["equal", "unequal"]
    variants: list[VariantCoverageDetail]


class CampaignExperimentReadout(BaseModel):
    experiment: CampaignExperimentRead
    readout_kind: Literal["descriptive_observation"] = "descriptive_observation"
    variants: list[VariantReadout]
    coverage_summary: list[CoverageMetricSummary]


def _coverage_classification(
    minimum_coverage_percent: float,
    maximum_coverage_percent: float,
) -> tuple[Literal["complete", "partial", "unavailable"], Literal["equal", "unequal"]]:
    completeness: Literal["complete", "partial", "unavailable"] = (
        "unavailable" if maximum_coverage_percent == 0
        else "complete" if minimum_coverage_percent == 100
        else "partial"
    )
    balance: Literal["equal", "unequal"] = (
        "equal" if minimum_coverage_percent == maximum_coverage_percent else "unequal"
    )
    return completeness, balance


def _spreadsheet_safe(value: Any) -> Any:
    """Prevent user-controlled CSV text from being evaluated as a spreadsheet formula."""
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)):
        return value
    text_value = str(value)
    if text_value.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@", "\t", "\r", "\n"}:
        return "'" + text_value
    return text_value


def _readout_csv_content(readout: CampaignExperimentReadout) -> str:
    headers = [
        "experiment_id", "experiment_name", "readout_kind", "period_start", "period_end",
        "allocation_method", "known_limitations", "variant_campaign_id",
        "variant_campaign_name", "variant_label", "is_control", "metric_role", "metric",
        "currency", "value", "delta_vs_control", "percent_change_vs_control", "status",
        "observed_days", "paired_days", "expected_days", "missing_days", "coverage_percent",
        "coverage_delta_vs_control_percentage_points", "metric_per_assigned", "metric_per_exposed",
        "metric_per_assigned_delta_vs_control", "metric_per_exposed_delta_vs_control",
        "missing_dates", "source_labels",
    ]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    experiment = readout.experiment
    for variant in readout.variants:
        metrics = [("primary", experiment.primary_metric, variant)] + [
            ("guardrail", item.metric, item) for item in variant.guardrails
        ]
        for role, metric, observation in metrics:
            writer.writerow(_spreadsheet_safe(value) for value in [
                experiment.id, experiment.name, readout.readout_kind,
                experiment.period_start, experiment.period_end,
                experiment.allocation_method, experiment.known_limitations,
                variant.campaign_id, variant.campaign_name, variant.label,
                variant.is_control, role, metric, observation.currency,
                observation.value, observation.delta_vs_control,
                observation.percent_change_vs_control, observation.status,
                observation.observed_days, observation.paired_days,
                observation.expected_days, observation.missing_days,
                observation.coverage_percent,
                observation.coverage_delta_vs_control_percentage_points,
                variant.metric_per_assigned if role == "primary" else None,
                variant.metric_per_exposed if role == "primary" else None,
                variant.metric_per_assigned_delta_vs_control if role == "primary" else None,
                variant.metric_per_exposed_delta_vs_control if role == "primary" else None,
                json.dumps([day.isoformat() for day in observation.missing_dates]),
                json.dumps(observation.source_labels, ensure_ascii=False),
            ])
        for role, metric, observation in (
            ("assignment", "assigned_count", variant.assignment),
            ("exposure", "exposure_count", variant.exposure),
        ):
            writer.writerow(_spreadsheet_safe(value) for value in [
                experiment.id, experiment.name, readout.readout_kind,
                experiment.period_start, experiment.period_end,
                experiment.allocation_method, experiment.known_limitations,
                variant.campaign_id, variant.campaign_name, variant.label,
                variant.is_control, role, metric, None, observation.count,
                None, None, observation.status, observation.observed_days, 0,
                observation.expected_days, observation.missing_days,
                observation.coverage_percent, None,
                json.dumps([day.isoformat() for day in observation.missing_dates]),
                json.dumps(observation.source_labels, ensure_ascii=False),
            ])
    return "\ufeff" + output.getvalue()


async def _require_permission(
    context: TenantSessionContext, permission: str, organization_unit_id: UUID
) -> None:
    if not await has_crm_permission(
        context, permission_key=permission, organization_unit_id=organization_unit_id
    ):
        raise HTTPException(status_code=403, detail="Campaign experiment is not authorized for this organization scope")


def _metric_value(
    metric: str,
    currency: str | None,
    rows: list[CRMMarketingCampaignMeasurement],
    commerce_events: list[CRMProductCommerceEvent] | None = None,
) -> tuple[int | Decimal | None, int, int]:
    commerce_events = commerce_events or []
    if metric == "paid_order_count":
        orders = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        return (len(orders) if orders else None, len({event.occurred_at.date() for event in commerce_events if event.event_kind == "paid"}), 0)
    if metric == "paid_amount":
        matching = [event for event in commerce_events if event.event_kind == "paid" and event.currency == currency]
        return (
            sum((event.amount for event in matching), Decimal("0")) if matching else None,
            len({event.occurred_at.date() for event in matching}),
            0,
        )
    if metric == "net_paid_amount":
        matching = [event for event in commerce_events if event.currency == currency and event.event_kind in {"paid", "refunded"}]
        if not matching:
            return None, 0, 0
        value = sum(
            (event.amount if event.event_kind == "paid" else -event.amount for event in matching),
            Decimal("0"),
        )
        return value, len({event.occurred_at.date() for event in matching}), 0
    if metric == "net_paid_amount_per_paid_order":
        matching = [event for event in commerce_events if event.currency == currency and event.event_kind in {"paid", "refunded"}]
        paid_orders = {
            (event.source_product, event.order_reference)
            for event in matching if event.event_kind == "paid"
        }
        if not paid_orders:
            return None, 0, 0
        net_amount = sum(
            (event.amount if event.event_kind == "paid" else -event.amount for event in matching),
            Decimal("0"),
        )
        value = (net_amount / Decimal(len(paid_orders))).quantize(Decimal("0.000001"))
        return value, len({event.occurred_at.date() for event in matching}), 0
    if metric == "average_paid_order_value":
        order_amounts: dict[tuple[str, str], Decimal] = {}
        for event in commerce_events:
            if event.event_kind == "paid" and event.currency == currency:
                key = (event.source_product, event.order_reference)
                order_amounts[key] = order_amounts.get(key, Decimal("0")) + event.amount
        value = (
            (sum(order_amounts.values(), Decimal("0")) / Decimal(len(order_amounts))).quantize(Decimal("0.000001"))
            if order_amounts else None
        )
        return value, len({event.occurred_at.date() for event in commerce_events if event.event_kind == "paid" and event.currency == currency}), 0
    if metric == "refunded_order_count":
        orders = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        return (len(orders) if commerce_events else None, len({event.occurred_at.date() for event in commerce_events}), 0)
    if metric == "matched_refund_order_rate_percent":
        paid = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        refunded = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        value = (Decimal(len(paid & refunded) * 100) / Decimal(len(refunded))).quantize(Decimal("0.0001")) if refunded else None
        return value, len({event.occurred_at.date() for event in commerce_events if event.event_kind == "refunded"}), 0
    if metric == "matched_paid_refund_order_count":
        paid = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        refunded = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        matched = paid & refunded
        qualifying = [event for event in commerce_events if event.event_kind in {"paid", "refunded"} and (event.source_product, event.order_reference) in matched]
        return (len(matched) if paid or refunded else None,
                len({event.occurred_at.date() for event in qualifying}), 0)
    if metric == "paid_order_refund_match_rate_percent":
        paid = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        refunded = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        value = (Decimal(len(paid & refunded) * 100) / Decimal(len(paid))).quantize(Decimal("0.0001")) if paid else None
        return value, len({event.occurred_at.date() for event in commerce_events if event.event_kind == "paid"}), 0
    if metric in {"unmatched_refund_order_count", "paid_order_without_refund_count"}:
        paid = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        refunded = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        denominator = refunded if metric == "unmatched_refund_order_count" else paid
        unmatched = refunded - paid if metric == "unmatched_refund_order_count" else paid - refunded
        event_kind = "refunded" if metric == "unmatched_refund_order_count" else "paid"
        return (len(unmatched) if denominator else None,
                len({event.occurred_at.date() for event in commerce_events if event.event_kind == event_kind and (event.source_product, event.order_reference) in unmatched}),
                0)
    if metric == "average_refund_per_order":
        order_amounts: dict[tuple[str, str], Decimal] = {}
        for event in commerce_events:
            if event.event_kind == "refunded" and event.currency == currency:
                key = (event.source_product, event.order_reference)
                order_amounts[key] = order_amounts.get(key, Decimal("0")) + event.amount
        value = (
            (sum(order_amounts.values(), Decimal("0")) / Decimal(len(order_amounts))).quantize(Decimal("0.000001"))
            if order_amounts else None
        )
        return value, len({event.occurred_at.date() for event in commerce_events if event.event_kind == "refunded" and event.currency == currency}), 0
    if metric == "refund_to_paid_amount_percent":
        paid: dict[tuple[str, str], Decimal] = {}
        refunded: dict[tuple[str, str], Decimal] = {}
        for event in commerce_events:
            if event.currency != currency:
                continue
            key = (event.source_product, event.order_reference)
            if event.event_kind == "paid":
                paid[key] = paid.get(key, Decimal("0")) + event.amount
            elif event.event_kind == "refunded":
                refunded[key] = refunded.get(key, Decimal("0")) + event.amount
        matched = paid.keys() & refunded.keys()
        paid_total = sum((paid[key] for key in matched), Decimal("0"))
        refund_total = sum((refunded[key] for key in matched), Decimal("0"))
        value = (refund_total * 100 / paid_total).quantize(Decimal("0.0001")) if paid_total > 0 else None
        paired_events = [
            event for event in commerce_events
            if event.currency == currency
            and (event.source_product, event.order_reference) in matched
        ]
        return value, len({event.occurred_at.date() for event in paired_events}), 0
    if metric == "refunded_order_rate_percent":
        paid = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        refunded = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        value = (Decimal(len(paid & refunded) * 100) / Decimal(len(paid))).quantize(Decimal("0.0001")) if paid else None
        return value, len({event.occurred_at.date() for event in commerce_events if event.event_kind == "paid"}), 0
    if metric == "refund_amount":
        matching = [event for event in commerce_events if event.event_kind == "refunded" and event.currency == currency]
        return (
            sum((event.amount for event in matching), Decimal("0")) if matching else None,
            len({event.occurred_at.date() for event in matching}),
            0,
        )
    if metric in COUNT_METRICS:
        values = [getattr(row, metric) for row in rows if getattr(row, metric) is not None]
        return (sum(values) if values else None, len(values), 0)
    if metric == "click_through_rate_percent":
        paired = [row for row in rows if row.clicks is not None and row.impressions is not None]
        clicks = sum((row.clicks for row in paired), 0)
        impressions = sum((row.impressions for row in paired), 0)
        value = (Decimal(clicks * 100) / Decimal(impressions)).quantize(Decimal("0.0001")) if paired and impressions > 0 else None
        return value, len(paired), len(paired)
    if metric == "conversion_rate_per_click_percent":
        paired = [row for row in rows if row.conversions is not None and row.clicks is not None]
        conversions = sum((row.conversions for row in paired), 0)
        clicks = sum((row.clicks for row in paired), 0)
        value = (Decimal(conversions * 100) / Decimal(clicks)).quantize(Decimal("0.0001")) if paired and clicks > 0 else None
        return value, len(paired), len(paired)
    if metric in {"cost_per_lead", "cost_per_conversion"}:
        outcome = "leads" if metric == "cost_per_lead" else "conversions"
        paired = [
            row for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
            and getattr(row, outcome) is not None
        ]
        spend = sum((row.actual_spend_amount for row in paired), Decimal("0"))
        outcomes = sum((getattr(row, outcome) for row in paired), 0)
        value = (spend / Decimal(outcomes)).quantize(Decimal("0.000001")) if paired and outcomes > 0 else None
        return value, len(paired), len(paired)
    if metric == "roas":
        paired = [
            row for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
            and row.attributed_revenue_amount is not None and row.attributed_revenue_currency == currency
        ]
        spend = sum((row.actual_spend_amount for row in paired), Decimal("0"))
        revenue = sum((row.attributed_revenue_amount for row in paired), Decimal("0"))
        value = (revenue / spend).quantize(Decimal("0.000001")) if paired and spend > 0 else None
        return value, len(paired), len(paired)
    if metric == "net_paid_to_spend":
        net_by_day: dict[date, Decimal] = {}
        for event in commerce_events:
            if event.currency == currency and event.event_kind in {"paid", "refunded"}:
                net_by_day[event.occurred_at.date()] = net_by_day.get(event.occurred_at.date(), Decimal("0")) + (
                    event.amount if event.event_kind == "paid" else -event.amount
                )
        spend_by_day = {
            row.measured_on: row.actual_spend_amount
            for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
        }
        paired_days = net_by_day.keys() & spend_by_day.keys()
        spend = sum((spend_by_day[day] for day in paired_days), Decimal("0"))
        net = sum((net_by_day[day] for day in paired_days), Decimal("0"))
        value = (net / spend).quantize(Decimal("0.000001")) if paired_days and spend > 0 else None
        return value, len(paired_days), len(paired_days)
    if metric == "incentive_cost":
        paired = [
            row for row in rows
            if row.incentive_cost_amount is not None
            and row.incentive_cost_currency == currency
        ]
        value = sum((row.incentive_cost_amount for row in paired), Decimal("0")) if paired else None
        return value, len(paired), len(paired)
    if metric == "refunded_amount":
        paired = [row for row in rows if row.refunded_amount is not None and row.refunded_currency == currency]
        value = sum((row.refunded_amount for row in paired), Decimal("0")) if paired else None
        return value, len(paired), len(paired)
    raise ValueError("Unsupported experiment metric")


def _metric_coverage(
    metric: str,
    currency: str | None,
    rows: list[CRMMarketingCampaignMeasurement],
    period_start: date,
    period_end: date,
    commerce_events: list[CRMProductCommerceEvent] | None = None,
) -> tuple[int, int, float, list[date], list[str]]:
    """Describe daily source coverage for the observations used by one metric."""
    commerce_events = commerce_events or []
    if metric == "paid_order_count":
        qualifying = [event for event in commerce_events if event.event_kind == "paid"]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "paid_amount":
        qualifying = [event for event in commerce_events if event.event_kind == "paid" and event.currency == currency]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "net_paid_amount":
        qualifying = [event for event in commerce_events if event.currency == currency and event.event_kind in {"paid", "refunded"}]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "net_paid_amount_per_paid_order":
        qualifying = [event for event in commerce_events if event.currency == currency and event.event_kind in {"paid", "refunded"}]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "average_paid_order_value":
        qualifying = [event for event in commerce_events if event.event_kind == "paid" and event.currency == currency]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "refunded_order_count":
        qualifying = [event for event in commerce_events if event.event_kind == "refunded"]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        observed_days = len(available_dates)
        return (
            expected_days, len(missing_dates),
            round(observed_days * 100 / expected_days, 2) if expected_days else 0.0,
            missing_dates, sorted({event.source_product for event in qualifying}),
        )
    if metric == "matched_refund_order_rate_percent":
        qualifying = [event for event in commerce_events if event.event_kind == "refunded"]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "matched_paid_refund_order_count":
        paid = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        refunded = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        matched = paid & refunded
        qualifying = [event for event in commerce_events if event.event_kind in {"paid", "refunded"} and (event.source_product, event.order_reference) in matched]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "paid_order_refund_match_rate_percent":
        qualifying = [event for event in commerce_events if event.event_kind == "paid"]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric in {"unmatched_refund_order_count", "paid_order_without_refund_count"}:
        paid = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "paid"}
        refunded = {(event.source_product, event.order_reference) for event in commerce_events if event.event_kind == "refunded"}
        unmatched = refunded - paid if metric == "unmatched_refund_order_count" else paid - refunded
        event_kind = "refunded" if metric == "unmatched_refund_order_count" else "paid"
        qualifying = [
            event for event in commerce_events
            if event.event_kind == event_kind and (event.source_product, event.order_reference) in unmatched
        ]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "average_refund_per_order":
        qualifying = [event for event in commerce_events if event.event_kind == "refunded" and event.currency == currency]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "refund_to_paid_amount_percent":
        currency_events = [event for event in commerce_events if event.currency == currency]
        paid_orders = {(event.source_product, event.order_reference) for event in currency_events if event.event_kind == "paid"}
        refunded_orders = {(event.source_product, event.order_reference) for event in currency_events if event.event_kind == "refunded"}
        matched = paid_orders & refunded_orders
        qualifying = [event for event in currency_events if (event.source_product, event.order_reference) in matched]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted({event.source_product for event in qualifying}))
    if metric == "refunded_order_rate_percent":
        qualifying = [event for event in commerce_events if event.event_kind == "paid"]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        return (
            expected_days, len(missing_dates),
            round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
            missing_dates, sorted({event.source_product for event in qualifying}),
        )
    if metric == "refund_amount":
        qualifying = [event for event in commerce_events if event.event_kind == "refunded" and event.currency == currency]
        available_dates = {event.occurred_at.date() for event in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        observed_days = len(available_dates)
        return (
            expected_days, len(missing_dates),
            round(observed_days * 100 / expected_days, 2) if expected_days else 0.0,
            missing_dates, sorted({event.source_product for event in qualifying}),
        )
    if metric in COUNT_METRICS:
        qualifying = [row for row in rows if getattr(row, metric) is not None]
    elif metric == "click_through_rate_percent":
        qualifying = [row for row in rows if row.clicks is not None and row.impressions is not None]
    elif metric == "conversion_rate_per_click_percent":
        qualifying = [row for row in rows if row.conversions is not None and row.clicks is not None]
    elif metric in {"cost_per_lead", "cost_per_conversion"}:
        outcome = "leads" if metric == "cost_per_lead" else "conversions"
        qualifying = [
            row for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
            and getattr(row, outcome) is not None
        ]
    elif metric == "roas":
        qualifying = [
            row for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
            and row.attributed_revenue_amount is not None and row.attributed_revenue_currency == currency
        ]
    elif metric == "net_paid_to_spend":
        commerce_days = {
            event.occurred_at.date()
            for event in commerce_events
            if event.currency == currency and event.event_kind in {"paid", "refunded"}
        }
        qualifying = [
            row for row in rows
            if row.actual_spend_amount is not None and row.actual_spend_currency == currency
            and row.measured_on in commerce_days
        ]
        available_dates = {row.measured_on for row in qualifying}
        expected_dates = [period_start + timedelta(days=index) for index in range((period_end - period_start).days + 1)]
        missing_dates = [day for day in expected_dates if day not in available_dates]
        expected_days = len(expected_dates)
        sources = {row.source_label for row in qualifying} | {
            event.source_product for event in commerce_events
            if event.currency == currency and event.event_kind in {"paid", "refunded"}
            and event.occurred_at.date() in available_dates
        }
        return (expected_days, len(missing_dates), round(len(available_dates) * 100 / expected_days, 2) if expected_days else 0.0,
                missing_dates, sorted(sources))
    elif metric == "incentive_cost":
        qualifying = [
            row for row in rows
            if row.incentive_cost_amount is not None
            and row.incentive_cost_currency == currency
        ]
    elif metric == "refunded_amount":
        qualifying = [row for row in rows if row.refunded_amount is not None and row.refunded_currency == currency]
    else:
        raise ValueError("Unsupported experiment metric")
    available_dates = {row.measured_on for row in qualifying}
    expected_dates = [period_start + timedelta(days=index)
                      for index in range((period_end - period_start).days + 1)]
    missing_dates = [day for day in expected_dates if day not in available_dates]
    expected_days = len(expected_dates)
    observed_days = len(available_dates)
    coverage_percent = round(observed_days * 100 / expected_days, 2) if expected_days else 0.0
    return (
        expected_days, len(missing_dates), coverage_percent, missing_dates,
        sorted({row.source_label for row in qualifying}),
    )


def _delivery_efficiency(value: int | Decimal | None, denominator: int | None) -> Decimal | None:
    """Normalize a recorded metric by a reported assignment or exposure count."""
    if value is None or denominator is None or denominator <= 0:
        return None
    return (Decimal(value) / Decimal(denominator)).quantize(Decimal("0.000001"))


def _delivery_count_readout(
    field: Literal["assigned_count", "exposure_count"],
    rows: list[CRMMarketingCampaignMeasurement],
    period_start: date,
    period_end: date,
) -> DeliveryCountReadout:
    qualifying = [row for row in rows if getattr(row, field) is not None]
    available_dates = {row.measured_on for row in qualifying}
    expected_dates = [
        period_start + timedelta(days=index)
        for index in range((period_end - period_start).days + 1)
    ]
    missing_dates = [day for day in expected_dates if day not in available_dates]
    expected_days = len(expected_dates)
    observed_days = len(available_dates)
    return DeliveryCountReadout(
        count=sum(getattr(row, field) for row in qualifying) if qualifying else None,
        status="available" if qualifying else "no_data",
        observed_days=observed_days,
        expected_days=expected_days,
        missing_days=len(missing_dates),
        coverage_percent=round(observed_days * 100 / expected_days, 2) if expected_days else 0.0,
        missing_dates=missing_dates,
        source_labels=sorted({row.source_label for row in qualifying}),
    )


@router.post("", response_model=CampaignExperimentRead, status_code=201,
             operation_id="createCRMMarketingCampaignExperiment")
async def create_campaign_experiment(
    payload: CampaignExperimentCreate,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignExperimentRead:
    await _require_permission(context, "crm.campaign:manage", payload.organization_unit_id)
    if payload.primary_metric in COMMERCE_METRICS or any(
        item.metric in COMMERCE_METRICS for item in payload.guardrails
    ):
        await _require_permission(context, "crm.commerce_event:view", payload.organization_unit_id)
    campaigns = (await context.session.scalars(
        select(CRMMarketingCampaign).where(
            CRMMarketingCampaign.tenant_id == context.access.tenant_id,
            CRMMarketingCampaign.organization_unit_id == payload.organization_unit_id,
            CRMMarketingCampaign.id.in_([variant.campaign_id for variant in payload.variants]),
        )
    )).all()
    if len(campaigns) != len(payload.variants):
        raise HTTPException(status_code=422, detail="All experiment campaigns must exist in the selected organization")
    signatures = {(campaign.segment_id, campaign.objective_key, campaign.channel) for campaign in campaigns}
    if len(signatures) != 1:
        raise HTTPException(
            status_code=422,
            detail="Experiment variants must share the same segment, objective, and channel",
        )
    segment = await context.session.scalar(select(CRMProfileSegment).where(
        CRMProfileSegment.tenant_id == context.access.tenant_id,
        CRMProfileSegment.id == campaigns[0].segment_id,
        CRMProfileSegment.organization_unit_id == payload.organization_unit_id,
    ))
    if segment is None:
        raise HTTPException(status_code=422, detail="The shared experiment audience segment is unavailable")
    audience_snapshot = {
        "segment_id": str(segment.id),
        "segment_name": segment.name,
        "criteria": segment.criteria,
    }

    experiment = CRMMarketingCampaignExperiment(
        id=uuid4(), tenant_id=context.access.tenant_id,
        organization_unit_id=payload.organization_unit_id,
        name=payload.name, hypothesis=payload.hypothesis,
        primary_metric=payload.primary_metric, currency=payload.currency,
        guardrail_metrics=[item.model_dump() for item in payload.guardrails],
        allocation_method=payload.allocation_method,
        known_limitations=payload.known_limitations,
        audience_snapshot=audience_snapshot,
        period_start=payload.period_start, period_end=payload.period_end,
    )
    context.session.add(experiment)
    await context.session.flush()
    context.session.add_all([
        CRMMarketingCampaignExperimentVariant(
            id=uuid4(), tenant_id=context.access.tenant_id,
            organization_unit_id=payload.organization_unit_id,
            experiment_id=experiment.id, campaign_id=variant.campaign_id,
            label=variant.label, is_control=variant.is_control,
        )
        for variant in payload.variants
    ])
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_campaign_experiment.created",
        target_type="crm_marketing_campaign_experiment",
        target_key=str(experiment.id),
        organization_unit_id=payload.organization_unit_id,
        before_state=None,
        after_state={
            "primary_metric": payload.primary_metric,
            "period_start": payload.period_start.isoformat(),
            "period_end": payload.period_end.isoformat(),
            "variant_count": len(payload.variants),
            "guardrails": [item.model_dump() for item in payload.guardrails],
            "allocation_method": payload.allocation_method,
            "known_limitations": payload.known_limitations,
            "audience_segment_id": str(segment.id),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return CampaignExperimentRead.model_validate(experiment)


@router.get("", response_model=list[CampaignExperimentListItem],
            operation_id="listCRMMarketingCampaignExperiments")
async def list_campaign_experiments(
    context: TenantSessionContext = Depends(require_tenant_session),
    organization_unit_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[CampaignExperimentListItem]:
    permitted_scopes = crm_scope_ids(context, permission_key="crm.campaign:view")
    if organization_unit_id is not None and organization_unit_id not in permitted_scopes:
        raise HTTPException(status_code=403, detail="Campaign experiment is not authorized for this organization scope")
    statement = (
        select(CRMMarketingCampaignExperiment)
        .where(
            CRMMarketingCampaignExperiment.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignExperiment.organization_unit_id.in_(permitted_scopes),
        )
        .order_by(CRMMarketingCampaignExperiment.created_at.desc(),
                  CRMMarketingCampaignExperiment.id)
    )
    if organization_unit_id is not None:
        statement = statement.where(
            CRMMarketingCampaignExperiment.organization_unit_id == organization_unit_id
        )
    experiments = (await context.session.scalars(statement.limit(limit).offset(offset))).all()
    result: list[CampaignExperimentListItem] = []
    for experiment in experiments:
        variants = (await context.session.execute(
            select(CRMMarketingCampaignExperimentVariant, CRMMarketingCampaign.name)
            .join(CRMMarketingCampaign, CRMMarketingCampaign.id == CRMMarketingCampaignExperimentVariant.campaign_id)
            .where(
                CRMMarketingCampaignExperimentVariant.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignExperimentVariant.experiment_id == experiment.id,
            )
            .order_by(CRMMarketingCampaignExperimentVariant.is_control.desc(),
                      CRMMarketingCampaignExperimentVariant.label)
        )).all()
        result.append(CampaignExperimentListItem(
            experiment=CampaignExperimentRead.model_validate(experiment),
            variants=[
                ExperimentVariantRead(
                    campaign_id=variant.campaign_id, campaign_name=campaign_name,
                    label=variant.label, is_control=variant.is_control,
                )
                for variant, campaign_name in variants
            ],
        ))
    return result


@router.get("/{experiment_id}/readout", response_model=CampaignExperimentReadout,
            operation_id="readCRMMarketingCampaignExperiment")
async def read_campaign_experiment(
    experiment_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CampaignExperimentReadout:
    experiment = await context.session.scalar(
        select(CRMMarketingCampaignExperiment).where(
            CRMMarketingCampaignExperiment.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignExperiment.id == experiment_id,
        )
    )
    if experiment is None:
        raise HTTPException(status_code=404, detail="Campaign experiment not found")
    await _require_permission(context, "crm.campaign:view", experiment.organization_unit_id)
    guardrail_configs = experiment.guardrail_metrics or []
    uses_commerce_metrics = experiment.primary_metric in COMMERCE_METRICS or any(
        item["metric"] in COMMERCE_METRICS for item in guardrail_configs
    )
    if uses_commerce_metrics:
        await _require_permission(context, "crm.commerce_event:view", experiment.organization_unit_id)

    variant_rows = (await context.session.execute(
        select(CRMMarketingCampaignExperimentVariant, CRMMarketingCampaign.name)
        .join(CRMMarketingCampaign, CRMMarketingCampaign.id == CRMMarketingCampaignExperimentVariant.campaign_id)
        .where(
            CRMMarketingCampaignExperimentVariant.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignExperimentVariant.organization_unit_id == experiment.organization_unit_id,
            CRMMarketingCampaignExperimentVariant.experiment_id == experiment.id,
        )
        .order_by(CRMMarketingCampaignExperimentVariant.is_control.desc(),
                  CRMMarketingCampaignExperimentVariant.label)
    )).all()
    campaign_ids = [variant.campaign_id for variant, _ in variant_rows]
    measurements_by_campaign: dict[UUID, list[CRMMarketingCampaignMeasurement]] = {
        campaign_id: [] for campaign_id in campaign_ids
    }
    commerce_by_campaign: dict[UUID, list[CRMProductCommerceEvent]] = {
        campaign_id: [] for campaign_id in campaign_ids
    }
    if campaign_ids:
        measurements = (await context.session.scalars(
            select(CRMMarketingCampaignMeasurement).where(
                CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
                CRMMarketingCampaignMeasurement.organization_unit_id == experiment.organization_unit_id,
                CRMMarketingCampaignMeasurement.campaign_id.in_(campaign_ids),
                CRMMarketingCampaignMeasurement.measured_on >= experiment.period_start,
                CRMMarketingCampaignMeasurement.measured_on <= experiment.period_end,
            ).order_by(CRMMarketingCampaignMeasurement.measured_on)
        )).all()
        for measurement in measurements:
            measurements_by_campaign[measurement.campaign_id].append(measurement)
        if uses_commerce_metrics:
            start_at = datetime.combine(experiment.period_start, time.min, tzinfo=timezone.utc)
            end_at = datetime.combine(experiment.period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
            commerce_events = (await context.session.scalars(
                select(CRMProductCommerceEvent).where(
                    CRMProductCommerceEvent.tenant_id == context.access.tenant_id,
                    CRMProductCommerceEvent.organization_unit_id == experiment.organization_unit_id,
                    CRMProductCommerceEvent.campaign_id.in_(campaign_ids),
                    CRMProductCommerceEvent.event_kind.in_(("paid", "refunded")),
                    CRMProductCommerceEvent.occurred_at >= start_at,
                    CRMProductCommerceEvent.occurred_at < end_at,
                ).order_by(CRMProductCommerceEvent.occurred_at, CRMProductCommerceEvent.id)
            )).all()
            for event in commerce_events:
                commerce_by_campaign[event.campaign_id].append(event)

    control_variant = next((variant for variant, _ in variant_rows if variant.is_control), None)
    control_value: int | Decimal | None = None
    control_coverage_percent: float | None = None
    if control_variant is not None:
        control_value, _, _ = _metric_value(
            experiment.primary_metric, experiment.currency,
            measurements_by_campaign[control_variant.campaign_id],
            commerce_by_campaign[control_variant.campaign_id],
        )
        control_coverage_percent = _metric_coverage(
            experiment.primary_metric, experiment.currency,
            measurements_by_campaign[control_variant.campaign_id],
            experiment.period_start, experiment.period_end,
            commerce_by_campaign[control_variant.campaign_id],
        )[2]
    readouts: list[VariantReadout] = []
    guardrail_controls = {
        (item["metric"], item.get("currency")): _metric_value(
            item["metric"], item.get("currency"),
            measurements_by_campaign[control_variant.campaign_id],
            commerce_by_campaign[control_variant.campaign_id],
        )[0]
        for item in guardrail_configs
    } if control_variant is not None else {}
    guardrail_control_coverage = {
        (item["metric"], item.get("currency")): _metric_coverage(
            item["metric"], item.get("currency"),
            measurements_by_campaign[control_variant.campaign_id],
            experiment.period_start, experiment.period_end,
            commerce_by_campaign[control_variant.campaign_id],
        )[2]
        for item in guardrail_configs
    } if control_variant is not None else {}
    for variant, campaign_name in variant_rows:
        value, observed_days, paired_days = _metric_value(
            experiment.primary_metric, experiment.currency,
            measurements_by_campaign[variant.campaign_id],
            commerce_by_campaign[variant.campaign_id],
        )
        delta = value - control_value if value is not None and control_value is not None else None
        percent = (
            round(float(delta) / abs(float(control_value)) * 100, 4)
            if delta is not None and control_value != 0 else None
        )
        guardrail_readouts = []
        for item in guardrail_configs:
            metric, currency = item["metric"], item.get("currency")
            metric_rows = measurements_by_campaign[variant.campaign_id]
            guard_value, guard_days, guard_paired = _metric_value(
                metric, currency, metric_rows, commerce_by_campaign[variant.campaign_id]
            )
            expected_days, missing_days, coverage_percent, missing_dates, source_labels = _metric_coverage(
                metric, currency, metric_rows, experiment.period_start, experiment.period_end,
                commerce_by_campaign[variant.campaign_id],
            )
            control_guard_coverage = guardrail_control_coverage.get((metric, currency))
            guard_control = guardrail_controls.get((metric, currency))
            guard_delta = guard_value - guard_control if guard_value is not None and guard_control is not None else None
            guard_percent = (
                round(float(guard_delta) / abs(float(guard_control)) * 100, 4)
                if guard_delta is not None and guard_control != 0 else None
            )
            guardrail_readouts.append(GuardrailMetricReadout(
                metric=metric, currency=currency, value=guard_value,
                delta_vs_control=guard_delta, percent_change_vs_control=guard_percent,
                status="available" if guard_value is not None else "no_data",
                observed_days=guard_days, paired_days=guard_paired,
                expected_days=expected_days, missing_days=missing_days,
                coverage_percent=coverage_percent,
                coverage_delta_vs_control_percentage_points=(
                    round(coverage_percent - control_guard_coverage, 2)
                    if control_guard_coverage is not None else None
                ),
                missing_dates=missing_dates,
                source_labels=source_labels,
            ))
        expected_days, missing_days, coverage_percent, missing_dates, source_labels = _metric_coverage(
            experiment.primary_metric, experiment.currency,
            measurements_by_campaign[variant.campaign_id],
            experiment.period_start, experiment.period_end,
            commerce_by_campaign[variant.campaign_id],
        )
        readouts.append(VariantReadout(
            campaign_id=variant.campaign_id, campaign_name=campaign_name,
            label=variant.label, is_control=variant.is_control,
            value=value, delta_vs_control=delta,
            percent_change_vs_control=percent, currency=experiment.currency,
            status="available" if value is not None else "no_data",
            observed_days=observed_days, paired_days=paired_days,
            expected_days=expected_days, missing_days=missing_days,
            coverage_percent=coverage_percent,
            coverage_delta_vs_control_percentage_points=(
                round(coverage_percent - control_coverage_percent, 2)
                if control_coverage_percent is not None else None
            ),
            missing_dates=missing_dates,
            source_labels=source_labels,
            assignment=_delivery_count_readout(
                "assigned_count", measurements_by_campaign[variant.campaign_id],
                experiment.period_start, experiment.period_end,
            ),
            exposure=_delivery_count_readout(
                "exposure_count", measurements_by_campaign[variant.campaign_id],
                experiment.period_start, experiment.period_end,
            ),
            guardrails=guardrail_readouts,
        ))
    control_readout = next((item for item in readouts if item.is_control), None)
    control_assigned_rate = (
        _delivery_efficiency(control_readout.value, control_readout.assignment.count)
        if control_readout else None
    )
    control_exposed_rate = (
        _delivery_efficiency(control_readout.value, control_readout.exposure.count)
        if control_readout else None
    )
    for item in readouts:
        item.metric_per_assigned = _delivery_efficiency(item.value, item.assignment.count)
        item.metric_per_exposed = _delivery_efficiency(item.value, item.exposure.count)
        item.metric_per_assigned_delta_vs_control = (
            item.metric_per_assigned - control_assigned_rate
            if item.metric_per_assigned is not None and control_assigned_rate is not None else None
        )
        item.metric_per_exposed_delta_vs_control = (
            item.metric_per_exposed - control_exposed_rate
            if item.metric_per_exposed is not None and control_exposed_rate is not None else None
        )

    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_campaign_experiment.readout_viewed",
        target_type="crm_marketing_campaign_experiment",
        target_key=str(experiment.id),
        organization_unit_id=experiment.organization_unit_id,
        before_state=None,
        after_state={
            "primary_metric": experiment.primary_metric,
            "period_start": experiment.period_start.isoformat(),
            "period_end": experiment.period_end.isoformat(),
            "variant_count": len(readouts),
            "guardrail_count": len(guardrail_configs),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    coverage_summary = []
    metric_configs = [(experiment.primary_metric, experiment.currency)] + [
        (item["metric"], item.get("currency")) for item in guardrail_configs
    ]
    for metric, currency in metric_configs:
        variant_coverage = []
        for variant in readouts:
            if metric == experiment.primary_metric and currency == experiment.currency:
                source = variant
            else:
                source = next(
                    guardrail for guardrail in variant.guardrails
                    if guardrail.metric == metric and guardrail.currency == currency
                )
            variant_coverage.append(VariantCoverageDetail(
                campaign_id=variant.campaign_id,
                label=variant.label,
                is_control=variant.is_control,
                coverage_percent=source.coverage_percent,
                expected_days=source.expected_days,
                missing_days=source.missing_days,
                missing_dates=source.missing_dates,
                source_labels=source.source_labels,
            ))
        coverage_values = [item.coverage_percent for item in variant_coverage]
        minimum_coverage = min(coverage_values)
        maximum_coverage = max(coverage_values)
        completeness, coverage_balance = _coverage_classification(
            minimum_coverage, maximum_coverage
        )
        coverage_summary.append(CoverageMetricSummary(
            metric=metric, currency=currency,
            variant_count=len(readouts),
            variants_with_missing_days=sum(value < 100 for value in coverage_values),
            minimum_coverage_percent=minimum_coverage,
            maximum_coverage_percent=maximum_coverage,
            coverage_spread_percentage_points=round(maximum_coverage - minimum_coverage, 2),
            completeness=completeness,
            coverage_balance=coverage_balance,
            variants=variant_coverage,
        ))
    return CampaignExperimentReadout(
        experiment=CampaignExperimentRead.model_validate(experiment),
        variants=readouts,
        coverage_summary=coverage_summary,
    )


@router.get("/{experiment_id}/readout.csv", response_class=Response,
            operation_id="exportCRMMarketingCampaignExperimentReadoutCsv")
async def export_campaign_experiment_readout_csv(
    experiment_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> Response:
    readout = await read_campaign_experiment(experiment_id, context)
    context.session.add(AuditEvent(
        tenant_id=context.access.tenant_id,
        actor_kind="user", actor_identity_id=context.access.identity_id,
        actor_membership_id=context.access.membership_id,
        action_key="crm_marketing_campaign_experiment.readout_exported",
        target_type="crm_marketing_campaign_experiment",
        target_key=str(experiment_id),
        organization_unit_id=readout.experiment.organization_unit_id,
        before_state=None,
        after_state={
            "format": "csv",
            "variant_count": len(readout.variants),
            "metric_row_count": sum(1 + len(variant.guardrails) for variant in readout.variants),
        },
        correlation_id=None,
    ))
    await context.session.flush()
    return Response(
        content=_readout_csv_content(readout),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="campaign-experiment-{experiment_id}.csv"'
        },
    )
