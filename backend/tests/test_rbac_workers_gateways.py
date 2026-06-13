import pytest
from django.urls import reverse

from accounts.models import AccessLevel, ResourceGrant, ScopeType
from gateways.models import Gateway
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
    return Worker.objects.create(name="worker-rbac-wg", hostname="worker-rbac-wg.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="tenant-rbac-wg",
        headscale_host="hs-rbac-wg.example.com",
        headplane_host="hp-rbac-wg.example.com",
        db_name="hs_rbac_wg",
        worker=worker,
    )


@pytest.fixture
def gateway(tenant):
    return Gateway.objects.create(tenant=tenant, hostname="gateway-rbac-wg")


@pytest.mark.django_db
def test_viewer_is_denied_workers_and_gateways_api(
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

    workers_response = client.get(reverse("worker-list"))
    gateways_response = client.get(reverse("gateway-list"))

    assert workers_response.status_code == 403
    assert gateways_response.status_code == 403


@pytest.mark.django_db
def test_viewer_is_denied_lifecycle_provision_actions(
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

    response = client.post(reverse("tenant-verify", kwargs={"tenant_id": tenant.id}))

    assert response.status_code == 403


@pytest.mark.django_db
def test_editor_with_worker_edit_grant_can_access_worker_views(
    client,
    admin_user,
    editor_user,
    worker,
):
    _grant(
        user=editor_user,
        scope_type=ScopeType.WORKER,
        scope_id=worker.id,
        access_level=AccessLevel.EDIT,
        granted_by=admin_user,
    )
    client.force_login(editor_user)

    list_response = client.get(reverse("worker-list"))
    summary_response = client.get(reverse("worker-tenant-summary", kwargs={"worker_id": worker.id}))

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [str(worker.id)]
    assert summary_response.status_code == 200


@pytest.mark.django_db
def test_editor_with_tenant_grant_can_read_gateway_detail(
    client,
    admin_user,
    editor_user,
    tenant,
    gateway,
):
    _grant(
        user=editor_user,
        scope_type=ScopeType.TENANT,
        scope_id=tenant.id,
        access_level=AccessLevel.VIEW,
        granted_by=admin_user,
    )
    client.force_login(editor_user)

    response = client.get(reverse("gateway-detail", kwargs={"gateway_id": gateway.id}))

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(gateway.id)
