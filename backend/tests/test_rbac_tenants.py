import pytest
from django.urls import reverse

from accounts.models import AccessLevel, ResourceGrant, ScopeType
from agents.models import Agent, AgentType
from tenants.models import Tenant
from workers.models import Worker


def _grant(*, user, scope_type, scope_id, access_level, granted_by):
    return ResourceGrant.objects.create(
        user=user,
        scope_type=scope_type,
        scope_id=scope_id,
        access_level=access_level,
        granted_by=granted_by,
    )


@pytest.fixture
def worker():
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_rb1",
        token_hash="1" * 64,
    )
    return Worker.objects.create(
        name="worker-rbac-tenant",
        hostname="worker-rbac.example.com",
        agent=agent,
    )


@pytest.fixture
def other_worker():
    return Worker.objects.create(name="worker-rbac-other", hostname="other.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="tenant-rbac-a",
        headscale_host="hs-rbac-a.example.com",
        headplane_host="hp-rbac-a.example.com",
        db_name="hs_rbac_a",
        worker=worker,
        bootstrap_output_ref="worker-output://rbac/a/bootstrap",
        bootstrap_secrets={
            "api_key": "hskey-api-rbac-a",
            "auth_key_gateway": "hskey-gw-rbac-a",
            "auth_key_workspace": "hskey-ws-rbac-a",
            "admin_user_id": "admin-a",
        },
    )


@pytest.fixture
def other_tenant(other_worker):
    return Tenant.objects.create(
        slug="tenant-rbac-b",
        headscale_host="hs-rbac-b.example.com",
        headplane_host="hp-rbac-b.example.com",
        db_name="hs_rbac_b",
        worker=other_worker,
    )


@pytest.mark.django_db
def test_viewer_list_is_scoped_to_granted_tenants(client, admin_user, viewer_user, tenant, other_tenant):
    _grant(
        user=viewer_user,
        scope_type=ScopeType.TENANT,
        scope_id=tenant.id,
        access_level=AccessLevel.VIEW,
        granted_by=admin_user,
    )
    client.force_login(viewer_user)

    response = client.get(reverse("tenant-list"))

    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()]
    assert slugs == ["tenant-rbac-a"]


@pytest.mark.django_db
def test_viewer_is_read_only_on_tenants(client, admin_user, viewer_user, tenant):
    _grant(
        user=viewer_user,
        scope_type=ScopeType.TENANT,
        scope_id=tenant.id,
        access_level=AccessLevel.VIEW,
        granted_by=admin_user,
    )
    client.force_login(viewer_user)

    response = client.patch(
        reverse("tenant-detail", kwargs={"pk": tenant.id}),
        data={"db_name": "forbidden_change"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_editor_can_create_tenant_only_on_granted_worker(client, admin_user, editor_user, worker):
    _grant(
        user=editor_user,
        scope_type=ScopeType.WORKER,
        scope_id=worker.id,
        access_level=AccessLevel.EDIT,
        granted_by=admin_user,
    )
    client.force_login(editor_user)

    response = client.post(
        reverse("tenant-list"),
        data={
            "slug": "tenant-rbac-created",
            "headscale_host": "hs-created.example.com",
            "headplane_host": "hp-created.example.com",
            "db_name": "hs_created",
            "worker": str(worker.id),
            "desired_config": {},
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    assert Tenant.objects.filter(slug="tenant-rbac-created").exists()


@pytest.mark.django_db
def test_viewer_tenant_detail_includes_bootstrap_secret_fields_when_granted(
    client,
    admin_user,
    viewer_user,
    tenant,
):
    _grant(
        user=viewer_user,
        scope_type=ScopeType.TENANT,
        scope_id=tenant.id,
        access_level=AccessLevel.VIEW,
        granted_by=admin_user,
    )
    client.force_login(viewer_user)

    response = client.get(reverse("tenant-detail", kwargs={"pk": tenant.id}))

    assert response.status_code == 200
    info = response.json()["bootstrap_info"]
    assert info is not None
    assert info["api_key"] == "hskey-api-rbac-a"
    assert info["auth_key_gateway"] == "hskey-gw-rbac-a"
    assert info["auth_key_workspace"] == "hskey-ws-rbac-a"
    assert info["admin_user_id"] == "admin-a"
