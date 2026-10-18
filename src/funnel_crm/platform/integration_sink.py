"""PostgreSQL-backed durable idempotent product event inbox."""

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from funnel_crm.api.v1.integrations import (
    EventReceipt,
    ProductEventEnvelope,
    VerifiedProductConnection,
)
from funnel_crm.platform.integration_payload_crypto import (
    IntegrationPayloadCryptoError,
    IntegrationPayloadKeyring,
)
from funnel_crm.platform.models import IntegrationEventInbox


class PostgresProductEventSink:
    """Commit an event receipt before acknowledging the verified producer."""

    def __init__(
        self,
        session_factory: async_sessionmaker[Any],
        *,
        keyring: IntegrationPayloadKeyring | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._keyring = keyring

    async def accept(
        self,
        connection: VerifiedProductConnection,
        event: ProductEventEnvelope,
    ) -> EventReceipt:
        keyring = self._keyring
        if keyring is None:
            try:
                keyring = IntegrationPayloadKeyring.from_environment()
            except IntegrationPayloadCryptoError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Integration payload encryption is unavailable",
                ) from exc

        canonical_event = json.dumps(
            event.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest_key_id, event_digest = keyring.digest(canonical_event)
        try:
            payload_key_id, encrypted_payload = keyring.encrypt(
                tenant_id=connection.tenant_id,
                event_id=event.event_id,
                source_product=event.source_product,
                event_type=event.event_type,
                contract_name=event.contract_name,
                contract_version=event.contract_version,
                payload=event.payload,
            )
        except IntegrationPayloadCryptoError as exc:
            raise HTTPException(
                status_code=503,
                detail="Integration payload encryption is unavailable",
            ) from exc

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "SELECT set_config('app.tenant_id', :tenant_id, true), "
                        "set_config('app.integration_connection_id', :connection_id, true)"
                    ),
                    {
                        "tenant_id": str(connection.tenant_id),
                        "connection_id": str(connection.connection_id),
                    },
                )
                statement = (
                    insert(IntegrationEventInbox)
                    .values(
                        tenant_id=connection.tenant_id,
                        connection_id=connection.connection_id,
                        event_id=event.event_id,
                        source_product=event.source_product,
                        event_type=event.event_type,
                        contract_name=event.contract_name,
                        contract_version=event.contract_version,
                        correlation_id=event.correlation_id,
                        occurred_at=event.occurred_at,
                        payload={},
                        payload_key_id=payload_key_id,
                        encrypted_payload=encrypted_payload,
                        event_digest=event_digest,
                        event_digest_key_id=digest_key_id,
                        processing_status="received",
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            IntegrationEventInbox.tenant_id,
                            IntegrationEventInbox.source_product,
                            IntegrationEventInbox.event_id,
                        ]
                    )
                    .returning(IntegrationEventInbox.id)
                )
                inserted_id = await session.scalar(statement)
                if inserted_id is not None:
                    duplicate = False
                else:
                    stored_digest_row = (
                        await session.execute(
                            select(
                                IntegrationEventInbox.event_digest,
                                IntegrationEventInbox.event_digest_key_id,
                            ).where(
                                IntegrationEventInbox.tenant_id == connection.tenant_id,
                                IntegrationEventInbox.source_product == event.source_product,
                                IntegrationEventInbox.event_id == event.event_id,
                            )
                        )
                    ).one_or_none()
                    if stored_digest_row is None:
                        raise RuntimeError("Conflicting integration event could not be read back")
                    stored_digest, stored_key_id = stored_digest_row
                    if stored_key_id is None:
                        # Rows accepted before keyed digests used plain SHA-256.
                        expected_digest = hashlib.sha256(canonical_event).digest()
                    else:
                        _, expected_digest = keyring.digest(
                            canonical_event, key_id=stored_key_id
                        )
                    if stored_digest != expected_digest:
                        raise HTTPException(
                            status_code=409,
                            detail="Event ID was already used with a different envelope",
                        )
                    duplicate = True

        return EventReceipt(event_id=event.event_id, duplicate=duplicate)
