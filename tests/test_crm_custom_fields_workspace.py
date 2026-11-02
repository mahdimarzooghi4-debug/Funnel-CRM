from fastapi.testclient import TestClient
from funnel_crm.main import app


def test_custom_fields_page_and_script_are_registered_and_secure():
    with TestClient(app) as client:
        page = client.get('/workspace/crm-custom-fields')
        assert page.status_code == 200
        assert page.headers['cache-control'] == 'no-store'
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        assert 'lang="fa" dir="rtl"' in page.text
        assert 'id="field-form"' in page.text
        script = client.get('/assets/crm-custom-fields.js')
        assert script.status_code == 200
        assert 'javascript' in script.headers['content-type']
        assert 'innerHTML' not in script.text
        assert '"X-Workspace-ID"' in script.text
