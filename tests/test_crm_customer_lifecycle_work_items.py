from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from funnel_crm.api.v1.crm_work_items import router
from funnel_crm.platform.models import (
    CRMCustomerActivity,
    CRMProfile,
    Role,
    RoleAssignment,
    RolePermission,
    TenantRecord,
)
from funnel_crm.platform.tenant_context import AuthenticatedIdentity, tenant_session


def make_app(
    session_factory: async_sessionmaker[AsyncSession], identity: AuthenticatedIdentity
) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def add_test_identity(request: Request, call_next):
        request.state.authenticated_identity = identity
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_lifecycle_review_creates_only_still_eligible_scoped_work_items(
    runtime_session_factory: async_sessionmaker[AsyncSession],
    tenant_case: dict[str, object],
) -> None:
    tenant_id, root_id = tenant_case["workspace_a"], tenant_case["root_a"]
    identity = tenant_case["identity"]
    assert isinstance(tenant_id, UUID)
    assert isinstance(root_id, UUID)
    assert isinstance(identity, AuthenticatedIdentity)

    stale_id, recent_id, untracked_id = uuid4(), uuid4(), uuid4()
    profile_ids = (stale_id, recent_id, untracked_id)
    tenant_case["lifecycle_cleanup_profile_ids"] = profile_ids
    now = datetime.now(timezone.utc)

    async with tenant_session(
        runtime_session_factory, requested_tenant_id=tenant_id, identity=identity
    ) as context:
        context.session.add_all([
            TenantRecord(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                record_type="crm_profile",
            )
            for profile_id in profile_ids
        ])
        await context.session.flush()
        context.session.add_all([
            CRMProfile(
                id=profile_id,
                tenant_id=tenant_id,
                organization_unit_id=root_id,
                profile_kind="person",
                display_name=name,
                lifecycle_stage="customer",
            )
            for profile_id, name in (
                (stale_id, "Lifecycle stale work item"),
                (recent_id, "Lifecycle recently active"),
                (untracked_id, "Lifecycle untracked work item"),
            )
        ])
        await context.session.flush()
        context.session.add_all([
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=stale_id,
                source_product="funnel.store", source_event_id=uuid4(), campaign_id=None,
                activity_type="order.completed", channel="store",
                occurred_at=now - timedelta(days=45),
            ),
            CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=recent_id,
                source_product="funnel.web", source_event_id=uuid4(), campaign_id=None,
                activity_type="form.submitted", channel="online",
                occurred_at=now - timedelta(days=2),
            ),
        ])
        role = Role(tenant_id=tenant_id, name=f"Lifecycle executor {uuid4().hex[:8]}")
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
                for permission in (
                    "crm.profile:view",
                    "crm.work_item:create",
                    "crm.work_item:view",
                    "crm.work_item:record_outcome",
                    "crm.work_item:update",
                )
            ],
        ])
        await context.session.flush()

    app = make_app(runtime_session_factory, identity)
    endpoint = "/api/v1/crm/work-items/from-lifecycle-review"
    headers = {"X-Workspace-ID": str(tenant_id)}
    base_payload = {
        "organization_unit_id": str(root_id),
        "inactive_for_days": 30,
        "lifecycle_stage": "customer",
        "profile_kind": "person",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        stale_selection = await client.post(
            endpoint,
            headers=headers,
            json={**base_payload, "profile_ids": [str(stale_id), str(recent_id)]},
        )
        assert stale_selection.status_code == 409

        created = await client.post(
            endpoint,
            headers=headers,
            json={**base_payload, "profile_ids": [str(stale_id), str(untracked_id)]},
        )
        assert created.status_code == 201, created.text
        result = created.json()
        assert result["created_count"] == 2
        by_profile = {item["profile_id"]: item for item in result["items"]}
        stale_item = by_profile[str(stale_id)]
        assert stale_item["title"].endswith("Lifecycle stale work item")
        assert "Latest linked CRM activity" in stale_item["description"]
        untracked_item = by_profile[str(untracked_id)]
        assert "does not prove no interaction occurred" in untracked_item["description"]

        outcome_payload = {
            "request_id": str(uuid4()),
            "outcome_code": "contact_made",
            "channel": "phone",
            "notes": "  Customer asked for a follow-up next week.  ",
        }
        outcome_url = f"/api/v1/crm/work-items/{stale_item['id']}/outcomes"
        recorded = await client.post(outcome_url, headers=headers, json=outcome_payload)
        assert recorded.status_code == 201, recorded.text
        outcome = recorded.json()
        assert outcome["outcome_code"] == "contact_made"
        assert outcome["notes"] == "Customer asked for a follow-up next week."
        replay = await client.post(outcome_url, headers=headers, json=outcome_payload)
        assert replay.status_code == 201
        assert replay.json()["id"] == outcome["id"]
        conflicting_replay = await client.post(
            outcome_url,
            headers=headers,
            json={**outcome_payload, "outcome_code": "no_contact"},
        )
        assert conflicting_replay.status_code == 409
        listed = await client.get(outcome_url, headers=headers)
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [outcome["id"]]

        async with tenant_session(
            runtime_session_factory,
            requested_tenant_id=tenant_id,
            identity=identity,
        ) as context:
            context.session.add(CRMCustomerActivity(
                id=uuid4(), tenant_id=tenant_id, profile_id=stale_id,
                source_product="funnel.store", source_event_id=uuid4(), campaign_id=None,
                activity_type="order.completed", channel="store",
                occurred_at=datetime.now(timezone.utc),
            ))
        readout = await client.get(
            "/api/v1/crm/work-items/lifecycle-review-readout",
            headers=headers,
            params={"organization_unit_id": str(root_id)},
        )
        assert readout.status_code == 200, readout.text
        readout_data = readout.json()
        assert readout_data["review_item_count"] == 2
        assert readout_data["work_item_count_by_status"]["open"] == 2
        assert readout_data["recorded_activities_after_task_count"] == 1
        assert readout_data["profiles_with_recorded_activity_after_task_count"] == 1
        assert readout_data["follow_up_outcome_count_by_code"]["contact_made"] == 1
        assert "does not establish" in readout_data["interpretation"]

        occurred_at = datetime.fromisoformat(outcome["occurred_at"])
        performance = await client.get(
            "/api/v1/crm/work-items/lifecycle-review-performance",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "start_at": (occurred_at - timedelta(minutes=1)).isoformat(),
                "end_at": (occurred_at + timedelta(minutes=1)).isoformat(),
            },
        )
        assert performance.status_code == 200, performance.text
        performance_data = performance.json()
        assert performance_data["totals"] == {
            "outcome_count": 1,
            "work_item_count": 1,
            "profile_count": 1,
        }
        assert performance_data["breakdown"] == [{
            "recorded_by_membership_id": outcome["recorded_by_membership_id"],
            "channel": "phone",
            "outcome_code": "contact_made",
            "outcome_count": 1,
            "work_item_count": 1,
            "profile_count": 1,
        }]
        assert performance_data["window"]["end_at_is_exclusive"] is True
        assert "causal effectiveness" in performance_data["interpretation"]

        invalid_window = await client.get(
            "/api/v1/crm/work-items/lifecycle-review-performance",
            headers=headers,
            params={
                "organization_unit_id": str(root_id),
                "start_at": occurred_at.isoformat(),
                "end_at": occurred_at.isoformat(),
            },
        )
        assert invalid_window.status_code == 422

        duplicate_ids = await client.post(
            endpoint,
            headers=headers,
            json={**base_payload, "profile_ids": [str(stale_id), str(stale_id)]},
        )
        assert duplicate_ids.status_code == 422

        unauthorized = await client.post(
            endpoint,
            headers=headers,
            json={
                **base_payload,
                "organization_unit_id": str(uuid4()),
                "profile_ids": [str(stale_id)],
            },
        )
        assert unauthorized.status_code == 403
