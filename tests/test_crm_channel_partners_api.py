"""Partner registry authorization, audit, and concurrent-write regression coverage."""
import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from funnel_crm.api.v1.crm_channel_partners import router
from funnel_crm.platform.models import AuditEvent, CRMChannelPartner, Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import tenant_session


@pytest.mark.asyncio
async def test_partner_registry_scope_and_concurrent_updates(tenant_case):
    # Multiple connections are essential: a one-connection fixture would hide
    # lost updates by serializing requests before they reach the endpoint.
    engine = create_async_engine(os.environ['TEST_DATABASE_URL'], pool_size=3)

    @event.listens_for(engine.sync_engine, 'connect')
    def runtime_role(connection, _):
        cursor = connection.cursor()
        cursor.execute('SET ROLE funnel_crm_runtime')
        cursor.close()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.state.session_factory = factory

    @app.middleware('http')
    async def identity(request: Request, call_next):
        request.state.authenticated_identity = tenant_case['identity']
        return await call_next(request)

    app.include_router(router, prefix='/api/v1')
    tenant = tenant_case['workspace_a']
    root = tenant_case['root_a']
    headers = {'X-Workspace-ID': str(tenant)}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            payload = {'organization_unit_id': str(root), 'name': 'Partner', 'partner_type': 'agency', 'phone': 'private-phone'}
            assert (await client.post('/api/v1/crm/channel-partners', headers=headers, json=payload)).status_code == 403
            async with tenant_session(factory, requested_tenant_id=tenant, identity=tenant_case['identity']) as context:
                role = Role(tenant_id=tenant, name=f'Partner manager {uuid4()}')
                context.session.add(role)
                await context.session.flush()
                context.session.add(RoleAssignment(tenant_id=tenant, membership_id=context.access.membership_id, role_id=role.id, organization_unit_id=root))
                for permission in ('crm.partner:view', 'crm.partner:manage'):
                    context.session.add(RolePermission(tenant_id=tenant, role_id=role.id, permission_key=permission))
            response = await client.post('/api/v1/crm/channel-partners', headers=headers, json=payload)
            assert response.status_code == 201, response.text
            partner = response.json()
            path = '/api/v1/crm/channel-partners/' + partner['id']
            assert (await client.get(path, headers=headers)).status_code == 200
            denied = {**payload, 'organization_unit_id': str(tenant_case['root_b'])}
            assert (await client.post('/api/v1/crm/channel-partners', headers=headers, json=denied)).status_code == 403
            foreign = await client.get('/api/v1/crm/channel-partners', headers=headers, params={'organization_unit_id': str(tenant_case['root_b'])})
            assert foreign.json()['items'] == []
            results = await asyncio.gather(*[
                client.patch(path, headers=headers, json={'expected_version': partner['version'], 'name': name})
                for name in ('First writer', 'Second writer')
            ])
            assert sorted(result.status_code for result in results) == [200, 409]
            current = (await client.get(path, headers=headers)).json()
            winner = next(result.json() for result in results if result.status_code == 200)
            assert current['name'] == winner['name']
            assert current['version'] == partner['version'] + 1
            async with tenant_session(factory, requested_tenant_id=tenant, identity=tenant_case['identity']) as context:
                events = list(await context.session.scalars(select(AuditEvent).where(AuditEvent.target_key == partner['id'])))
                assert sorted(e.action_key for e in events) == ['crm_channel_partner.created', 'crm_channel_partner.updated']
                assert all('private-phone' not in str(e.after_state) for e in events)
    finally:
        try:
            async with tenant_session(factory, requested_tenant_id=tenant, identity=tenant_case['identity']) as context:
                await context.session.execute(delete(CRMChannelPartner).where(CRMChannelPartner.tenant_id == tenant))
        finally:
            await engine.dispose()
