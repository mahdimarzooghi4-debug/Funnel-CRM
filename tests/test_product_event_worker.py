from __future__ import annotations

from uuid import UUID

import pytest

from funnel_crm.platform.product_event_worker import (
    configured_poll_seconds,
    configured_tenant_ids,
)


def test_worker_requires_explicit_unique_workspace_scopes() -> None:
    tenant_id = UUID("11e54bf1-ecba-4bf6-9d02-6686d84a5d79")
    assert configured_tenant_ids(f" {tenant_id}, {tenant_id.hex} ") == (tenant_id,)
    with pytest.raises(ValueError, match="must contain"):
        configured_tenant_ids("")
    with pytest.raises(ValueError, match="invalid UUID"):
        configured_tenant_ids("not-a-uuid")
    with pytest.raises(ValueError, match="duplicate"):
        configured_tenant_ids(f"{tenant_id},{tenant_id}")


def test_worker_poll_interval_is_bounded() -> None:
    assert configured_poll_seconds("2.5") == 2.5
    with pytest.raises(ValueError, match="numeric"):
        configured_poll_seconds("soon")
    with pytest.raises(ValueError, match="between"):
        configured_poll_seconds("0.1")
