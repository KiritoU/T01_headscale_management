from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from agents.metrics_service import record_resource_sample
from agents.models import Agent, AgentType, ResourceSample
from gateways.models import Gateway
from tenants.models import Tenant
from workers.models import Worker


def _sample_metrics(**overrides):
    payload = {
        "cpu_percent": 33.3,
        "mem_percent": 44.4,
        "disk_percent": 55.5,
        "mem_total_bytes": 8_000_000_000,
        "mem_used_bytes": 3_500_000_000,
        "disk_total_bytes": 50_000_000_000,
        "disk_used_bytes": 27_000_000_000,
        "net_rx_bytes_per_sec": 512,
        "net_tx_bytes_per_sec": 256,
        "load_avg_1m": 0.8,
        "cpu_count": 2,
        "uptime_seconds": 900.0,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="metrics-admin",
        password="secret-pass",
        role="admin",
        is_staff=True,
    )


@pytest.fixture
def worker_with_agent(db):
    worker = Worker.objects.create(name="api-worker", hostname="api.vps.example.com")
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_api",
        token_hash="d" * 64,
    )
    worker.agent = agent
    worker.save(update_fields=["agent"])
    record_resource_sample(agent, _sample_metrics())
    return worker


@pytest.fixture
def gateway_with_agent(db, worker_with_agent):
    tenant = Tenant.objects.create(
        slug="metrics-tenant",
        headscale_host="hs.example.com",
        headplane_host="hp.example.com",
        db_name="hs_metrics",
        worker=worker_with_agent,
    )
    gateway = Gateway.objects.create(tenant=tenant, hostname="gw-metrics")
    agent = Agent.objects.create(
        agent_type=AgentType.GATEWAY,
        token_prefix="agnt_gw",
        token_hash="e" * 64,
    )
    gateway.agent = agent
    gateway.save(update_fields=["agent"])
    record_resource_sample(agent, _sample_metrics(cpu_percent=77.7))
    return gateway


@pytest.mark.django_db
class TestWorkerMetricsApi:
    def test_worker_metrics_requires_auth(self, client, worker_with_agent):
        client.logout()
        response = client.get(reverse("worker-metrics", kwargs={"worker_id": worker_with_agent.id}))
        assert response.status_code == 403

    def test_worker_metrics_returns_samples(self, client, admin_user, worker_with_agent):
        client.force_login(admin_user)
        response = client.get(reverse("worker-metrics", kwargs={"worker_id": worker_with_agent.id}))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["window_seconds"] > 0
        assert data["current"]["cpu_percent"] == 33.3
        assert len(data["samples"]) == 1
        assert data["samples"][0]["mem_percent"] == 44.4

    def test_worker_without_agent_returns_empty_metrics(self, client, admin_user):
        worker = Worker.objects.create(name="no-agent", hostname="pending.vps.example.com")
        client.force_login(admin_user)
        response = client.get(reverse("worker-metrics", kwargs={"worker_id": worker.id}))

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["current"] is None
        assert data["samples"] == []


@pytest.mark.django_db
class TestGatewayMetricsApi:
    def test_gateway_metrics_returns_samples(self, client, admin_user, gateway_with_agent):
        client.force_login(admin_user)
        response = client.get(
            reverse("gateway-metrics", kwargs={"gateway_id": gateway_with_agent.id}),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["current"]["cpu_percent"] == 77.7
        assert len(data["samples"]) == 1

    def test_gateway_metrics_honors_window_query(self, client, admin_user, gateway_with_agent):
        agent = gateway_with_agent.agent
        assert agent is not None
        ResourceSample.objects.filter(agent=agent).delete()
        older = timezone.now() - timedelta(hours=2)
        record_resource_sample(agent, _sample_metrics(cpu_percent=11.0), sampled_at=older)
        record_resource_sample(agent, _sample_metrics(cpu_percent=22.0))

        client.force_login(admin_user)
        response = client.get(
            reverse("gateway-metrics", kwargs={"gateway_id": gateway_with_agent.id}),
            data={"window": "1800"},
        )

        assert response.status_code == 200
        samples = response.json()["data"]["samples"]
        assert len(samples) == 1
        assert samples[0]["cpu_percent"] == 22.0
