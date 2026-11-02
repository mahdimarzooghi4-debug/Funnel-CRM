import httpx
import pytest
from uuid import uuid4
from funnel_crm.platform.models import CRMCustomFieldDefinition, Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import tenant_session
from test_crm_profile_api import make_app


@pytest.mark.asyncio
async def test_creation_schema_is_creator_scoped_and_supports_required_false(runtime_session_factory, tenant_case):
    tenant, root, identity = tenant_case['workspace_a'], tenant_case['root_a'], tenant_case['identity']
    app = make_app(runtime_session_factory, identity)
    headers = {'X-Workspace-ID': str(tenant)}
    params = {'organization_unit_id': str(root), 'profile_kind': 'person'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        denied = await client.get('/api/v1/crm/profiles/create-schema', headers=headers, params=params)
        assert denied.status_code == 403
        async with tenant_session(runtime_session_factory, requested_tenant_id=tenant, identity=identity) as context:
            role = Role(tenant_id=tenant, name=f'Profile creator {uuid4()}')
            context.session.add(role)
            await context.session.flush()
            context.session.add(RoleAssignment(tenant_id=tenant, membership_id=context.access.membership_id, role_id=role.id, organization_unit_id=root))
            context.session.add(RolePermission(tenant_id=tenant, role_id=role.id, permission_key='crm.profile:create'))
            for kind, key, active in [('person', 'required_flag', True), ('person', 'inactive_flag', False), ('organization', 'org_flag', True)]:
                context.session.add(CRMCustomFieldDefinition(tenant_id=tenant, entity_kind=kind, field_key=key, display_name=key, value_type='boolean', options=[], is_required=True, is_active=active))
        response = await client.get('/api/v1/crm/profiles/create-schema', headers=headers, params=params)
        assert response.status_code == 200, response.text
        assert [field['field_key'] for field in response.json()['items']] == ['required_flag']
        foreign = await client.get('/api/v1/crm/profiles/create-schema', headers=headers, params={**params, 'organization_unit_id': str(tenant_case['root_b'])})
        assert foreign.status_code == 403
        payload = {'organization_unit_id': str(root), 'profile_kind': 'person', 'display_name': 'Schema customer'}
        missing = await client.post('/api/v1/crm/profiles', headers=headers, json=payload)
        assert missing.status_code == 422
        created = await client.post('/api/v1/crm/profiles', headers=headers, json={**payload, 'custom_fields': {'required_flag': False}})
        assert created.status_code == 201, created.text
