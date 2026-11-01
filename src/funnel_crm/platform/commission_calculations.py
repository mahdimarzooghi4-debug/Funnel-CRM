"""Pure aggregation rules for commission calculation snapshots."""

from collections import defaultdict
from decimal import Decimal
from typing import Iterable
from uuid import UUID


def aggregate_commission_events(
    events: Iterable[object], *, seller_membership_id: UUID | None,
) -> dict[tuple[UUID | None, str], dict]:
    """Group paid/refund facts by seller and currency, retaining source IDs.

    A seller-scoped plan includes that seller and separately reports
    unattributed facts. Organization plans include all attributed sellers.
    Unattributed facts remain visible but are never included in a payout basis.
    """
    groups: dict[tuple[UUID | None, str], dict] = defaultdict(lambda: {
        "paid": Decimal("0"), "refunded": Decimal("0"), "ids": [],
    })
    for event in events:
        event_seller_id = event.seller_membership_id
        if seller_membership_id is not None and event_seller_id not in (None, seller_membership_id):
            continue
        group = groups[(event_seller_id, event.currency)]
        group["paid" if event.event_kind == "paid" else "refunded"] += event.amount
        group["ids"].append(str(event.source_event_id))
    return dict(groups)
