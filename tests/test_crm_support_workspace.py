from fastapi import FastAPI
from fastapi.testclient import TestClient
from funnel_crm.web.crm_support_workspace import router


def test_support_workspace_route_security_and_forms():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        page = client.get('/workspace/crm-support')
        assert page.status_code == 200
        assert page.headers['cache-control'] == 'no-store'
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        assert 'lang="fa" dir="rtl"' in page.text
        for name in ('case-form', 'queue', 'profile-next', 'next', 'overdue', 'history-panel', 'entry-form', 'history-next', 'sla-form', 'sla-result', 'planning-form', 'planning-due', 'ownership', 'customer-context', 'clear-customer'):
            assert f'id="{name}"' in page.text
        script = client.get('/assets/crm-support.js')
        assert script.status_code == 200
        assert 'javascript' in script.headers['content-type']
        assert 'innerHTML' not in script.text
        assert '"X-Workspace-ID"' in script.text
