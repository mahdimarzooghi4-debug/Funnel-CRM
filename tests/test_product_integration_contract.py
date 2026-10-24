from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from funnel_crm.api.v1.integrations import (
    ProductEventEnvelope,
    VerifiedProductConnection,
    authorize_product_event,
)


def make_event(**overrides) -> ProductEventEnvelope:
    fields = {
        "event_id": uuid4(),
        "tenant_id": uuid4(),
        "source_product": "funnel.store",
        "event_type": "order.created",
        "contract_name": "commerce.order",
        "contract_version": 1,
        "correlation_id": uuid4(),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"order_id": "ord-123"},
    }
    fields.update(overrides)
    return ProductEventEnvelope.model_validate(fields)


def make_connection(event: ProductEventEnvelope) -> VerifiedProductConnection:
    return VerifiedProductConnection(
        connection_id=uuid4(),
        tenant_id=event.tenant_id,
        source_product=event.source_product,
        allowed_event_types=frozenset({event.event_type}),
        supported_contract_versions=frozenset({(event.contract_name, event.contract_version)}),
    )


def test_event_contract_requires_timezone_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_event(occurred_at="2026-10-17T10:00:00")
    with pytest.raises(ValidationError):
        make_event(untrusted=True)


def test_connection_grants_event_only_to_its_workspace_and_scope() -> None:
    event = make_event()
    connection = make_connection(event)
    authorize_product_event(connection, event)

    for changed in (
        event.model_copy(update={"tenant_id": uuid4()}),
        event.model_copy(update={"source_product": "other.product"}),
        event.model_copy(update={"event_type": "customer.export"}),
        event.model_copy(update={"contract_version": 2}),
    ):
        with pytest.raises(HTTPException) as error:
            authorize_product_event(connection, changed)
        assert error.value.status_code == 403


def test_inactive_connection_is_denied() -> None:
    event = make_event()
    connection = make_connection(event)
    inactive = VerifiedProductConnection(
        **{**connection.__dict__, "active": False}
    )
    with pytest.raises(HTTPException) as error:
        authorize_product_event(inactive, event)
    assert error.value.status_code == 403


def test_payload_limit_is_enforced() -> None:
    with pytest.raises(ValidationError):
        make_event(payload={"large": "x" * (64 * 1024)})
