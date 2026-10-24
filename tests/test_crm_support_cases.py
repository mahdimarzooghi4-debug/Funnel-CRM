from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from funnel_crm.api.v1.crm_profiles import router as profile_router
from funnel_crm.api.v1.crm_support_cases import router as support_router
from funnel_crm.platform.models import Role, RoleAssignment, RolePermission
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(session_factory, identity: AuthenticatedIdentity) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(support_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_support_case_queue_tracks_assignment_deadline_and_status(
    runtime_session_factory, tenant_case
) -> None:
    tenant_id = tenant_case["workspace_a"]
    root_id = tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    permissions = (
        "crm.profile:create",
        "crm.support_case:view",
        "crm.support_case:create",
        "crm.support_case:update",
    )
    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        role = Role(tenant_id=tenant_id, name=f"Support manager {uuid4().hex[:8]}")
        context.session.add(role)
        await context.session.flush()
        context.session.add_all([
            RoleAssignment(
                tenant_id=tenant_id,
                membership_id=context.access.membership_id,
                role_id=role.id,
                organization_unit_id=root_id,
            ),
            *[
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_key=permission,
                )
                for permission in permissions
            ],
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    headers = {"X-Workspace-ID": str(tenant_id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        profile = await client.post(
            "/api/v1/crm/profiles",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "profile_kind": "person",
                "display_name": "Support customer",
            },
        )
        assert profile.status_code == 201, profile.text
        profile_id = profile.json()["id"]

        now = datetime.now(timezone.utc)
        created = await client.post(
            "/api/v1/crm/support-cases",
            headers=headers,
            json={
                "organization_unit_id": str(root_id),
                "profile_id": profile_id,
                "subject": "  Delayed order  ",
                "description": "Customer needs an update",
                "priority": "urgent",
                "response_due_at": (now - timedelta(minutes=20)).isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        case = created.json()
        assert case["subject"] == "Delayed order"
        assert case["status"] == "open"
        case_id = case["id"]

        overdue = await client.get(
            "/api/v1/crm/support-cases",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "overdue_only": True,
                "as_of": now.isoformat(),
            },
        )
        assert overdue.status_code == 200, overdue.text
        page = overdue.json()
        assert page["total"] == 1
        assert page["overdue_count"] == 1
        assert page["items"][0]["id"] == case_id

        progressed = await client.patch(
            f"/api/v1/crm/support-cases/{case_id}",
            headers=headers,
            json={"status": "in_progress"},
        )
        assert progressed.status_code == 200, progressed.text
        waiting = await client.patch(
            f"/api/v1/crm/support-cases/{case_id}",
            headers=headers,
            json={"status": "waiting_customer", "assigned_membership_id": None},
        )
        assert waiting.status_code == 200, waiting.text
        resolved = await client.patch(
            f"/api/v1/crm/support-cases/{case_id}",
            headers=headers,
            json={"status": "resolved"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["resolved_at"] is not None

        reopened = await client.patch(
            f"/api/v1/crm/support-cases/{case_id}",
            headers=headers,
            json={"status": "open"},
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["resolved_at"] is None

        closed = await client.patch(
            f"/api/v1/crm/support-cases/{case_id}",
            headers=headers,
            json={"status": "closed"},
        )
        assert closed.status_code == 200, closed.text
        rejected = await client.patch(
            f"/api/v1/crm/support-cases/{case_id}",
            headers=headers,
            json={"subject": "Cannot edit closed case"},
        )
        assert rejected.status_code == 409
