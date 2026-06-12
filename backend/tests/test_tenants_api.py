import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentType, CommandState
from agents.services import ack_command
from lifecycle.services import enqueue_bootstrap_tenant
from tenants.models import BootstrapStatus, Tenant, TenantHealth
from workers.models import Worker, WorkerStatus


@pytest.fixture
def worker(db):
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_ta1",
        token_hash="d" * 64,
    )
    return Worker.objects.create(
        name="worker-alpha",
        hostname="alpha.example.com",
        status=WorkerStatus.ONLINE,
        docker_reachable=True,
        agent=agent,
    )


@pytest.fixture
def tenant_payload(worker):
    return {
        "slug": "team-alpha",
        "headscale_host": "headscale-team-alpha.example.com",
        "headplane_host": "headplane-team-alpha.example.com",
        "db_name": "hs_team_alpha",
        "worker": str(worker.id),
        "bootstrap_status": BootstrapStatus.PENDING,
        "desired_config": {"replicas": 1, "region": "us-east"},
    }


@pytest.fixture
def tenant(worker, tenant_payload):
    return Tenant.objects.create(
        slug=tenant_payload["slug"],
        headscale_host=tenant_payload["headscale_host"],
        headplane_host=tenant_payload["headplane_host"],
        db_name=tenant_payload["db_name"],
        worker=worker,
        bootstrap_status=BootstrapStatus.BOOTSTRAPPED,
        desired_config=tenant_payload["desired_config"],
    )


@pytest.mark.django_db
class TestTenantListCreate:
    def test_list_tenants_empty(self, client):
        response = client.get(reverse("tenant-list"))

        assert response.status_code == 200
        assert response.json() == []

    def test_create_tenant(self, client, tenant_payload):
        response = client.post(
            reverse("tenant-list"),
            data=tenant_payload,
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["slug"] == tenant_payload["slug"]
        assert data["headscale_host"] == tenant_payload["headscale_host"]
        assert data["desired_config"] == tenant_payload["desired_config"]
        assert Tenant.objects.filter(slug=tenant_payload["slug"]).exists()

    def test_create_rejects_forbidden_desired_config_keys(self, client, tenant_payload):
        for forbidden_key in ("db_password", "SECRET_TOKEN", "authkey", "my_api_key"):
            payload = {
                **tenant_payload,
                "slug": f"team-{forbidden_key}",
                "desired_config": {forbidden_key: "x"},
            }
            response = client.post(
                reverse("tenant-list"),
                data=payload,
                content_type="application/json",
            )

            assert response.status_code == 400
            body = response.json()
            assert body["success"] is False
            assert body["error"]
            error_lower = body["error"].lower()
            assert "desired_config" in error_lower or forbidden_key.lower() in error_lower

    def test_create_rejects_nested_forbidden_desired_config_keys(self, client, tenant_payload):
        payload = {
            **tenant_payload,
            "slug": "team-nested-secret",
            "desired_config": {"settings": {"api_key": "leak"}},
        }
        response = client.post(
            reverse("tenant-list"),
            data=payload,
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "desired_config" in body["error"].lower()


@pytest.mark.django_db
class TestTenantDetail:
    def test_retrieve_tenant(self, client, tenant):
        response = client.get(reverse("tenant-detail", kwargs={"pk": tenant.id}))

        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == tenant.slug
        assert data["bootstrap_status"] == BootstrapStatus.BOOTSTRAPPED

    def test_retrieve_includes_bootstrap_info_from_acked_command(self, client, tenant):
        Tenant.objects.filter(pk=tenant.pk).update(bootstrap_status=BootstrapStatus.PENDING)
        tenant.refresh_from_db()
        command = enqueue_bootstrap_tenant(tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "bootstrap_status": BootstrapStatus.BOOTSTRAPPED,
                "bootstrap": {
                    "admin_user_id": "admin-alpha",
                    "api_key": "hskey-api-alpha",
                    "auth_key_gateway": "hskey-gateway-alpha",
                    "auth_key_workspace": "hskey-workspace-alpha",
                    "output_ref": tenant.bootstrap_output_ref,
                },
            },
        )

        response = client.get(reverse("tenant-detail", kwargs={"pk": tenant.id}))

        assert response.status_code == 200
        data = response.json()
        assert data["bootstrap_info"] is not None
        assert data["bootstrap_info"]["command_id"] == str(stored.id)
        assert data["bootstrap_info"]["admin_user_id"] == "admin-alpha"
        assert data["bootstrap_info"]["api_key"] == "hskey-api-alpha"
        assert data["bootstrap_info"]["auth_key_gateway"] == "hskey-gateway-alpha"
        assert data["bootstrap_info"]["auth_key_workspace"] == "hskey-workspace-alpha"

    def test_retrieve_includes_nested_health_read_only(self, client, tenant):
        now = timezone.now()
        TenantHealth.objects.create(
            tenant=tenant,
            probed_at=now,
            latency_ms=42,
            healthy=True,
            error_message="",
        )
        TenantHealth.objects.create(
            tenant=tenant,
            probed_at=now - timezone.timedelta(minutes=5),
            latency_ms=120,
            healthy=False,
            error_message="connection refused",
        )

        response = client.get(reverse("tenant-detail", kwargs={"pk": tenant.id}))

        assert response.status_code == 200
        data = response.json()
        assert "health_checks" in data
        assert len(data["health_checks"]) == 2
        assert data["health_checks"][0]["latency_ms"] == 42
        assert data["health_checks"][1]["healthy"] is False

    def test_list_excludes_health_checks(self, client, tenant):
        TenantHealth.objects.create(
            tenant=tenant,
            probed_at=timezone.now(),
            latency_ms=10,
            healthy=True,
        )

        response = client.get(reverse("tenant-list"))

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "health_checks" not in data[0]
        assert data[0]["worker_name"] == "worker-alpha"

    def test_update_tenant(self, client, tenant, worker):
        response = client.patch(
            reverse("tenant-detail", kwargs={"pk": tenant.id}),
            data={
                "bootstrap_status": BootstrapStatus.PROVISIONING,
                "desired_config": {"replicas": 2},
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["bootstrap_status"] == BootstrapStatus.PROVISIONING
        assert data["desired_config"] == {"replicas": 2}

    def test_delete_tenant(self, client, tenant):
        response = client.delete(reverse("tenant-detail", kwargs={"pk": tenant.id}))

        assert response.status_code == 204
        assert not Tenant.objects.filter(id=tenant.id).exists()

    def test_retrieve_not_found_returns_envelope(self, client):
        response = client.get(reverse("tenant-detail", kwargs={"pk": uuid.uuid4()}))

        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert body["error"]


@pytest.mark.django_db
class TestTenantFilters:
    def test_filter_by_bootstrap_status(self, client, worker):
        Tenant.objects.create(
            slug="pending-team",
            headscale_host="hs-p.example.com",
            headplane_host="hp-p.example.com",
            db_name="hs_p",
            worker=worker,
            bootstrap_status=BootstrapStatus.PENDING,
        )
        Tenant.objects.create(
            slug="booted-team",
            headscale_host="hs-b.example.com",
            headplane_host="hp-b.example.com",
            db_name="hs_b",
            worker=worker,
            bootstrap_status=BootstrapStatus.BOOTSTRAPPED,
        )

        response = client.get(reverse("tenant-list"), {"bootstrap_status": BootstrapStatus.PENDING})

        assert response.status_code == 200
        slugs = [item["slug"] for item in response.json()]
        assert slugs == ["pending-team"]

    def test_filter_by_worker(self, client, worker):
        other_worker = Worker.objects.create(name="worker-beta")
        Tenant.objects.create(
            slug="alpha-team",
            headscale_host="hs-a.example.com",
            headplane_host="hp-a.example.com",
            db_name="hs_a",
            worker=worker,
        )
        Tenant.objects.create(
            slug="beta-team",
            headscale_host="hs-bt.example.com",
            headplane_host="hp-bt.example.com",
            db_name="hs_bt",
            worker=other_worker,
        )

        response = client.get(reverse("tenant-list"), {"worker": str(worker.id)})

        assert response.status_code == 200
        slugs = [item["slug"] for item in response.json()]
        assert slugs == ["alpha-team"]

    def test_slug_search_filter(self, client, worker):
        Tenant.objects.create(
            slug="engineering-team",
            headscale_host="hs-e.example.com",
            headplane_host="hp-e.example.com",
            db_name="hs_e",
            worker=worker,
        )
        Tenant.objects.create(
            slug="sales-team",
            headscale_host="hs-s.example.com",
            headplane_host="hp-s.example.com",
            db_name="hs_s",
            worker=worker,
        )

        response = client.get(reverse("tenant-list"), {"slug": "engine"})

        assert response.status_code == 200
        slugs = [item["slug"] for item in response.json()]
        assert slugs == ["engineering-team"]
