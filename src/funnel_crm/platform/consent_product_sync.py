"""Durable, commit-ordered feed of CRM consent decisions to products."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from funnel_crm.platform.models import (
    CRMCommunicationConsentEvent,
    CRMConsentProductSyncOutbox,
    CRMConsentProductSyncSequence,
    ProductCustomerIdentity,
)


async def enqueue_consent_change_for_products(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    profile_id: UUID,
    consent_event_id: int,
    purpose_key: str,
    channel: str,
    decision: str,
    policy_version: str,
    decision_at: datetime,
    origin_product: str | None,
    source_event_id: UUID | None,
) -> int:
    """Append one feed row per product with a mapped identity.

    The sequence row is locked by the upsert until the caller's transaction
    commits, so a consumer cursor cannot pass an event that commits later with
    a lower sequence.
    """
    identities = (
        await session.scalars(
            select(ProductCustomerIdentity).where(
                ProductCustomerIdentity.tenant_id == tenant_id,
                ProductCustomerIdentity.profile_id == profile_id,
            )
        )
    ).all()
    queued = 0
    for identity in identities:
        sequence_table = CRMConsentProductSyncSequence.__table__
        sequence_statement = (
            pg_insert(CRMConsentProductSyncSequence)
            .values(
                tenant_id=tenant_id,
                recipient_product=identity.source_product,
                last_sequence=1,
            )
            .on_conflict_do_update(
                index_elements=[
                    sequence_table.c.tenant_id,
                    sequence_table.c.recipient_product,
                ],
                set_={"last_sequence": sequence_table.c.last_sequence + 1},
            )
            .returning(CRMConsentProductSyncSequence.last_sequence)
        )
        sequence = await session.scalar(sequence_statement)
        if sequence is None:
            raise RuntimeError("consent sync sequence allocation failed")
        session.add(
            CRMConsentProductSyncOutbox(
                tenant_id=tenant_id,
                recipient_product=identity.source_product,
                sequence=sequence,
                consent_event_id=consent_event_id,
                external_customer_id=identity.external_customer_id,
                purpose_key=purpose_key,
                channel=channel,
                decision=decision,
                policy_version=policy_version,
                decision_at=decision_at,
                source_product=origin_product,
                source_event_id=source_event_id,
            )
        )
        queued += 1
    return queued
