"""Preview and atomically import campaign performance CSV exports."""

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from funnel_crm.api.dependencies.tenant import require_tenant_session
from funnel_crm.api.v1.crm_campaign_measurements import (
    CampaignMeasurementUpsert,
    _require_permission,
)
from funnel_crm.platform.models import (
    AuditEvent,
    CRMMarketingCampaign,
    CRMMarketingCampaignMeasurement,
    CRMMarketingMeasurementImportBatch,
)
from funnel_crm.platform.tenant_context import TenantSessionContext

router = APIRouter(prefix="/crm/campaigns", tags=["CRM campaign measurement import"])
MAX_CSV_CHARS = 1_000_000
MAX_ROWS = 366
MAX_COUNT = 9223372036854775807
COUNT_COLUMNS = (
    "impressions", "reach", "clicks", "responses", "leads", "conversions",
    "assigned_count", "exposure_count",
)
MONEY_PAIRS = (
    ("actual_spend_amount", "actual_spend_currency"),
    ("attributed_revenue_amount", "attributed_revenue_currency"),
)
ALLOWED_COLUMNS = {
    "measured_on", "source_label", *COUNT_COLUMNS,
    "actual_spend_amount", "actual_spend_currency",
    "attributed_revenue_amount", "attributed_revenue_currency",
}


class CSVPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_content: str = Field(min_length=1, max_length=MAX_CSV_CHARS)


class CSVImportInput(CSVPreviewInput):
    idempotency_key: str = Field(min_length=1, max_length=80)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key must contain a non-whitespace character")
        return normalized


class CSVRowError(BaseModel):
    row_number: int
    detail: str


class ParsedMeasurementRow(BaseModel):
    measured_on: date
    source_label: str
    impressions: int | None
    reach: int | None
    clicks: int | None
    responses: int | None
    leads: int | None
    conversions: int | None
    assigned_count: int | None
    exposure_count: int | None
    actual_spend_amount: Decimal | None
    actual_spend_currency: str | None
    attributed_revenue_amount: Decimal | None
    attributed_revenue_currency: str | None


class CSVPreviewResult(BaseModel):
    valid: bool
    row_count: int
    would_create: int | None
    would_update: int | None
    rows: list[ParsedMeasurementRow]
    errors: list[CSVRowError]


class CSVImportResult(BaseModel):
    batch_id: UUID
    row_count: int
    created_count: int
    updated_count: int
    replayed: bool


def _parse_csv(csv_content: str) -> tuple[list[dict[str, object]], list[CSVRowError]]:
    if len(csv_content.encode("utf-8")) > MAX_CSV_CHARS:
        return [], [CSVRowError(row_number=1, detail="CSV exceeds the 1 MB import limit")]
    try:
        reader = csv.DictReader(StringIO(csv_content.lstrip(chr(65279))), strict=True)
        headers = reader.fieldnames
        if not headers:
            return [], [CSVRowError(row_number=1, detail="CSV header is required")]
        normalized_headers = [header.strip() if header is not None else "" for header in headers]
        if len(set(normalized_headers)) != len(normalized_headers):
            return [], [CSVRowError(row_number=1, detail="CSV has duplicate column names")]
        unknown = sorted(set(normalized_headers) - ALLOWED_COLUMNS)
        if unknown:
            return [], [CSVRowError(row_number=1, detail=f"Unknown columns: {', '.join(unknown)}")]
        missing = {"measured_on", "source_label"} - set(normalized_headers)
        if missing:
            return [], [CSVRowError(row_number=1, detail=f"Required columns missing: {', '.join(sorted(missing))}")]
        if not (set(COUNT_COLUMNS) & set(normalized_headers)) and not (
            {"actual_spend_amount", "attributed_revenue_amount"} & set(normalized_headers)
        ):
            return [], [CSVRowError(row_number=1, detail="CSV must include at least one metric column")]
        for amount_key, currency_key in MONEY_PAIRS:
            if (amount_key in normalized_headers) != (currency_key in normalized_headers):
                return [], [CSVRowError(row_number=1, detail=f"{amount_key} and {currency_key} columns must be included together")]

        reader.fieldnames = normalized_headers
        parsed: list[dict[str, object]] = []
        errors: list[CSVRowError] = []
        seen_dates: dict[date, int] = {}
        for row_number, raw_row in enumerate(reader, start=2):
            if row_number - 1 > MAX_ROWS:
                errors.append(CSVRowError(row_number=row_number, detail=f"CSV may contain at most {MAX_ROWS} data rows"))
                break
            if None in raw_row:
                errors.append(CSVRowError(row_number=row_number, detail="Row has more values than the header"))
                continue
            try:
                data: dict[str, object] = {}
                raw_date = (raw_row.get("measured_on") or "").strip()
                measured_on = date.fromisoformat(raw_date)
                for key in ALLOWED_COLUMNS - {"measured_on"}:
                    raw_value = (raw_row.get(key) or "").strip()
                    if key == "source_label":
                        data[key] = raw_value
                    elif key in COUNT_COLUMNS:
                        if not raw_value:
                            data[key] = None
                        else:
                            value = int(raw_value)
                            if value < 0 or value > MAX_COUNT:
                                raise ValueError(f"{key} must be between 0 and {MAX_COUNT}")
                            data[key] = value
                    elif key.endswith("_amount"):
                        if not raw_value:
                            data[key] = None
                        else:
                            try:
                                data[key] = Decimal(raw_value)
                            except InvalidOperation as exc:
                                raise ValueError(f"{key} must be a decimal number") from exc
                    else:
                        data[key] = raw_value or None
                validated = CampaignMeasurementUpsert.model_validate(data)
                row_data = {
                    "measured_on": measured_on,
                    **validated.model_dump(),
                }
                assert isinstance(measured_on, date)
                if measured_on in seen_dates:
                    errors.append(CSVRowError(
                        row_number=row_number,
                        detail=f"Duplicate measured_on date also appears on row {seen_dates[measured_on]}",
                    ))
                else:
                    seen_dates[measured_on] = row_number
                parsed.append(row_data)
            except (ValueError, ValidationError) as exc:
                errors.append(CSVRowError(row_number=row_number, detail=str(exc)))
            if len(errors) >= 100:
                errors.append(CSVRowError(row_number=row_number, detail="Further errors were omitted"))
                break
        if not parsed and not errors:
            errors.append(CSVRowError(row_number=2, detail="CSV contains no data rows"))
        return parsed, errors
    except csv.Error as exc:
        return [], [CSVRowError(row_number=1, detail=f"Malformed CSV: {exc}")]


async def _load_campaign(context: TenantSessionContext, campaign_id: UUID, *, lock: bool = False) -> CRMMarketingCampaign:
    query = select(CRMMarketingCampaign).where(
        CRMMarketingCampaign.tenant_id == context.access.tenant_id,
        CRMMarketingCampaign.id == campaign_id,
    )
    if lock:
        query = query.with_for_update()
    campaign = await context.session.scalar(query)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _parse_authorized(
    campaign_id: UUID,
    csv_content: str,
    context: TenantSessionContext,
) -> tuple[CRMMarketingCampaign, list[dict[str, object]], list[CSVRowError]]:
    campaign = await _load_campaign(context, campaign_id)
    await _require_permission(
        context, permission_key="crm.campaign:manage",
        organization_unit_id=campaign.organization_unit_id,
    )
    rows, errors = _parse_csv(csv_content)
    return campaign, rows, errors


@router.get(
    "/{campaign_id}/measurements/import-template",
    operation_id="getCRMMarketingCampaignMeasurementImportTemplate",
)
async def get_campaign_measurement_import_template(
    campaign_id: UUID,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> Response:
    campaign = await _load_campaign(context, campaign_id)
    await _require_permission(
        context, permission_key="crm.campaign:view",
        organization_unit_id=campaign.organization_unit_id,
    )
    template = (
        "measured_on,source_label,impressions,reach,clicks,responses,leads,conversions,assigned_count,exposure_count,"
        "actual_spend_amount,actual_spend_currency,attributed_revenue_amount,attributed_revenue_currency\n"
    )
    return Response(content=template, media_type="text/csv; charset=utf-8")


@router.post(
    "/{campaign_id}/measurements/import-preview",
    response_model=CSVPreviewResult,
    operation_id="previewCRMMarketingCampaignMeasurementImport",
)
async def preview_campaign_measurement_import(
    campaign_id: UUID,
    payload: CSVPreviewInput,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CSVPreviewResult:
    campaign, rows, errors = await _parse_authorized(campaign_id, payload.csv_content, context)
    if errors:
        return CSVPreviewResult(
            valid=False, row_count=len(rows), would_create=None, would_update=None,
            rows=[ParsedMeasurementRow(**row) for row in rows], errors=errors,
        )
    dates = [row["measured_on"] for row in rows]
    existing = (await context.session.scalars(
        select(CRMMarketingCampaignMeasurement.measured_on).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign.id,
            CRMMarketingCampaignMeasurement.measured_on.in_(dates),
        )
    )).all()
    existing_dates = set(existing)
    update_count = sum(1 for item in rows if item["measured_on"] in existing_dates)
    return CSVPreviewResult(
        valid=True,
        row_count=len(rows),
        would_create=len(rows) - update_count,
        would_update=update_count,
        rows=[ParsedMeasurementRow(**row) for row in rows],
        errors=[],
    )


@router.post(
    "/{campaign_id}/measurements/import",
    response_model=CSVImportResult,
    operation_id="importCRMMarketingCampaignMeasurements",
)
async def import_campaign_measurements(
    campaign_id: UUID,
    payload: CSVImportInput,
    context: TenantSessionContext = Depends(require_tenant_session),
) -> CSVImportResult:
    campaign, rows, errors = await _parse_authorized(campaign_id, payload.csv_content, context)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "CSV validation failed; no rows were imported", "errors": [error.model_dump() for error in errors]},
        )
    canonical_rows = sorted(rows, key=lambda item: item["measured_on"])
    digest = hashlib.sha256(
        json.dumps(canonical_rows, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    # Serialize imports for this campaign so an idempotency key is checked before any row is changed.
    campaign = await _load_campaign(context, campaign_id, lock=True)
    previous = await context.session.scalar(
        select(CRMMarketingMeasurementImportBatch).where(
            CRMMarketingMeasurementImportBatch.tenant_id == context.access.tenant_id,
            CRMMarketingMeasurementImportBatch.campaign_id == campaign.id,
            CRMMarketingMeasurementImportBatch.idempotency_key == payload.idempotency_key,
        )
    )
    if previous is not None:
        if previous.payload_sha256 != digest:
            raise HTTPException(status_code=409, detail="Idempotency key was already used with different CSV data")
        return CSVImportResult(
            batch_id=previous.id,
            row_count=previous.row_count,
            created_count=previous.created_count,
            updated_count=previous.updated_count,
            replayed=True,
        )

    existing_rows = (await context.session.scalars(
        select(CRMMarketingCampaignMeasurement).where(
            CRMMarketingCampaignMeasurement.tenant_id == context.access.tenant_id,
            CRMMarketingCampaignMeasurement.campaign_id == campaign.id,
            CRMMarketingCampaignMeasurement.measured_on.in_([item["measured_on"] for item in rows]),
        ).with_for_update()
    )).all()
    existing_by_date = {item.measured_on: item for item in existing_rows}
    created_count = 0
    updated_count = 0
    for row in rows:
        measured_on = row["measured_on"]
        measurement = existing_by_date.get(measured_on)
        if measurement is None:
            measurement = CRMMarketingCampaignMeasurement(
                id=uuid4(),
                tenant_id=context.access.tenant_id,
                organization_unit_id=campaign.organization_unit_id,
                campaign_id=campaign.id,
                measured_on=measured_on,
            )
            context.session.add(measurement)
            created_count += 1
        else:
            updated_count += 1
        for key, value in row.items():
            if key != "measured_on":
                setattr(measurement, key, value)

    batch = CRMMarketingMeasurementImportBatch(
        id=uuid4(),
        tenant_id=context.access.tenant_id,
        organization_unit_id=campaign.organization_unit_id,
        campaign_id=campaign.id,
        idempotency_key=payload.idempotency_key.strip(),
        payload_sha256=digest,
        row_count=len(rows),
        created_count=created_count,
        updated_count=updated_count,
    )
    context.session.add(batch)
    await context.session.flush()
    context.session.add(
        AuditEvent(
            tenant_id=context.access.tenant_id,
            actor_kind="user",
            actor_identity_id=context.access.identity_id,
            actor_membership_id=context.access.membership_id,
            action_key="crm_marketing_measurement_import.completed",
            target_type="crm_marketing_measurement_import_batch",
            target_key=str(batch.id),
            organization_unit_id=campaign.organization_unit_id,
            before_state=None,
            after_state={
                "campaign_id": str(campaign.id),
                "row_count": len(rows),
                "created_count": created_count,
                "updated_count": updated_count,
                "payload_sha256": digest,
            },
            correlation_id=None,
        )
    )
    await context.session.flush()
    return CSVImportResult(
        batch_id=batch.id,
        row_count=len(rows),
        created_count=created_count,
        updated_count=updated_count,
        replayed=False,
    )
