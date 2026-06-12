from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from agents.models import Agent, AgentType
from gateways.models import Gateway, GatewayStatus
from tenants.models import Tenant
from workers.models import Worker, WorkerStatus


@pytest.fixture
def worker(db):
    return Worker.objects.create(name="liveness-worker", hostname="liveness.example.com")


@pytest.fixture
def worker_agent(worker):
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="wk000001",
        token_hash="hash",
        poll_interval_seconds=15,
    )
    worker.agent = agent
    worker.status = WorkerStatus.ONLINE
    worker.last_heartbeat_at = timezone.now()
    worker.save(update_fields=["agent", "status", "last_heartbeat_at", "updated_at"])
    return agent


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="liveness-team",
        headscale_host="hs.example.com",
        headplane_host="hp.example.com",
        db_name="hs_liveness",
        worker=worker,
    )


@pytest.fixture
def gateway(tenant):
    return Gateway.objects.create(tenant=tenant, hostname="gw-liveness")


@pytest.fixture
def gateway_agent(gateway):
    agent = Agent.objects.create(
        agent_type=AgentType.GATEWAY,
        token_prefix="gw000001",
        token_hash="hash",
        poll_interval_seconds=15,
    )
    gateway.agent = agent
    gateway.status = GatewayStatus.ONLINE
    gateway.last_heartbeat_at = timezone.now()
    gateway.save(update_fields=["agent", "status", "last_heartbeat_at", "updated_at"])
    return agent


@pytest.mark.django_db
class TestAgentLiveness:
    def test_stale_worker_marked_offline_on_list(self, client, worker, worker_agent):
        stale_at = timezone.now() - timedelta(seconds=60)
        Worker.objects.filter(pk=worker.pk).update(last_heartbeat_at=stale_at)

        response = client.get(reverse("worker-list"))

        assert response.status_code == 200
        row = next(item for item in response.json() if item["id"] == str(worker.id))
        assert row["status"] == WorkerStatus.OFFLINE
        worker.refresh_from_db()
        assert worker.status == WorkerStatus.OFFLINE

    def test_stale_gateway_marked_offline_on_list(self, client, gateway, gateway_agent):
        stale_at = timezone.now() - timedelta(seconds=60)
        Gateway.objects.filter(pk=gateway.pk).update(last_heartbeat_at=stale_at)

        response = client.get(reverse("gateway-list"))

        assert response.status_code == 200
        body = response.json()
        row = next(item for item in body["data"] if item["id"] == str(gateway.id))
        assert row["status"] == GatewayStatus.OFFLINE
        gateway.refresh_from_db()
        assert gateway.status == GatewayStatus.OFFLINE

    def test_recent_heartbeat_stays_online(self, client, worker, worker_agent):
        response = client.get(reverse("worker-list"))

        assert response.status_code == 200
        row = next(item for item in response.json() if item["id"] == str(worker.id))
        assert row["status"] == WorkerStatus.ONLINE
