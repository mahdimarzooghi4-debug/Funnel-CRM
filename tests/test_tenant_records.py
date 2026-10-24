from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.platform.models import TenantRecord
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


@pytest.mark.asyncio
async def test_tenant_record_is_scoped_by_rls_and_org_foreign_key(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_a = tenant_case["workspace_a"]
    tenant_b = tenant_case["workspace_b"]
    root_a = tenant_case["root_a"]
    root_b = tenant_case["root_b"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_a, UUID)
    assert isinstance(tenant_b, UUID)
    assert isinstance(root_a, UUID)
    assert isinstance(root_b, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    record_id = uuid4()
    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_a,
        identity=identity,
    ) as context:
        record = TenantRecord(
            id=record_id,
            tenant_id=tenant_a,
            organization_unit_id=root_a,
            record_type="campaign",
        )
        context.session.add(record)
        await context.session.flush()
        assert await context.session.get(TenantRecord, record_id) is record

        # RLS blocks a forged tenant owner even when the caller has valid access
        # to a different tenant.
        async with context.session.begin_nested():
            context.session.add(
                TenantRecord(
                    tenant_id=tenant_b,
                    organization_unit_id=root_b,
                    record_type="campaign",
                )
            )
            with pytest.raises(DBAPIError):
                await context.session.flush()

        # The composite FK independently rejects an organization from another
        # tenant even when tenant_id itself passes the RLS check.
        async with context.session.begin_nested():
            context.session.add(
                TenantRecord(
                    tenant_id=tenant_a,
                    organization_unit_id=root_b,
                    record_type="campaign",
                )
            )
            with pytest.raises(DBAPIError):
                await context.session.flush()

    # With no transaction-local context, the non-owner runtime role sees none.
    async with runtime_session_factory() as session:
        async with session.begin():
            assert (await session.scalars(select(TenantRecord))).all() == []


@pytest.mark.asyncio
async def test_record_type_must_be_nonempty(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    async with tenant_session(
        runtime_session_factory,
        requested_tenant_id=tenant_id,
        identity=identity,
    ) as context:
        context.session.add(
            TenantRecord(
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                record_type="  ",
            )
        )
        with pytest.raises(DBAPIError):
            await context.session.flush()
