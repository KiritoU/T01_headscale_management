import pytest
from django.urls import reverse

from accounts.models import AccessLevel, ResourceGrant, ScopeType
from gateways.services import create_enrollment_token, register_gateway_from_token
from tenants.models import Tenant
from workers.models import Worker
from workers.services import create_worker_enrollment_token, register_worker_from_token


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
    return Worker.objects.create(name="worker-agent-enqueue", hostname="enqueue.vps.example.com")


@pytest.fixture
def enrolled_worker():
    creds = create_worker_enrollment_token("worker-agent-enrolled")
    enrolled, agent, _ = register_worker_from_token(creds.raw_token, hostname="enrolled.example.com")
    return enrolled, agent


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="tenant-agent-enqueue",
        headscale_host="hs-agent-enqueue.example.com",
        headplane_host="hp-agent-enqueue.example.com",
        db_name="hs_agent_enqueue",
        worker=worker,
    )


@pytest.fixture
def enrolled_gateway(tenant):
    creds = create_enrollment_token(tenant)
    gateway, agent, _ = register_gateway_from_token(creds.raw_token, hostname="gw-enqueue")
    return gateway, agent


@pytest.mark.django_db
def test_agent_command_enqueue_requires_session_auth(client, enrolled_worker):
    _worker, agent = enrolled_worker

    client.logout()
    response = client.post(
        reverse("agent-command-enqueue", kwargs={"agent_id": agent.id}),
        data={"command": "install_module", "payload": {"module": "docker"}},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_editor_with_worker_edit_grant_can_enqueue_worker_command(
    client,
    admin_user,
    editor_user,
    enrolled_worker,
):
    worker, agent = enrolled_worker
    _grant(
        user=editor_user,
        scope_type=ScopeType.WORKER,
        scope_id=worker.id,
        access_level=AccessLevel.EDIT,
        granted_by=admin_user,
    )
    client.force_login(editor_user)

    response = client.post(
        reverse("agent-command-enqueue", kwargs={"agent_id": agent.id}),
        data={"command": "install_module", "payload": {"module": "docker"}},
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["success"] is True


@pytest.mark.django_db
def test_editor_with_tenant_edit_grant_can_enqueue_gateway_command(
    client,
    admin_user,
    editor_user,
    tenant,
    enrolled_gateway,
):
    _gateway, agent = enrolled_gateway
    _grant(
        user=editor_user,
        scope_type=ScopeType.TENANT,
        scope_id=tenant.id,
        access_level=AccessLevel.EDIT,
        granted_by=admin_user,
    )
    client.force_login(editor_user)

    response = client.post(
        reverse("agent-command-enqueue", kwargs={"agent_id": agent.id}),
        data={"command": "scan_network", "payload": {"mode": "discover"}},
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["success"] is True


@pytest.mark.django_db
def test_viewer_cannot_enqueue_agent_commands(client, admin_user, viewer_user, enrolled_worker):
    worker, agent = enrolled_worker
    _grant(
        user=viewer_user,
        scope_type=ScopeType.WORKER,
        scope_id=worker.id,
        access_level=AccessLevel.VIEW,
        granted_by=admin_user,
    )
    client.force_login(viewer_user)

    response = client.post(
        reverse("agent-command-enqueue", kwargs={"agent_id": agent.id}),
        data={"command": "install_module", "payload": {"module": "docker"}},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_agent_register_requires_valid_enrollment_token(client, worker):
    client.logout()
    response = client.post(
        reverse("agent-register"),
        data={"agent_type": "worker", "worker_id": str(worker.id)},
        content_type="application/json",
    )

    assert response.status_code == 400
    body = response.json()
    assert "enrollment_token" in body["error"]


@pytest.mark.django_db
def test_agent_register_accepts_valid_worker_enrollment_token(client):
    creds = create_worker_enrollment_token("worker-register-valid")

    response = client.post(
        reverse("agent-register"),
        data={
            "agent_type": "worker",
            "enrollment_token": creds.raw_token,
            "hostname": "register-valid-worker",
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token"].startswith("agnt_")
    assert body["agent_id"]
