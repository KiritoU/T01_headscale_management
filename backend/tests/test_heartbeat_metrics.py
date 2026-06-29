from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from agents.metrics_service import record_resource_sample, resource_sample_retention_seconds
from agents.models import Agent, AgentType, ResourceSample
from gateways.models import Gateway
from tenants.models import Tenant
from workers.models import Worker


def _sample_metrics(**overrides):
    payload = {
        "cpu_percent": 42.5,
        "mem_percent": 55.0,
        "disk_percent": 61.0,
        "mem_total_bytes": 16_000_000_000,
        "mem_used_bytes": 8_800_000_000,
        "disk_total_bytes": 100_000_000_000,
        "disk_used_bytes": 61_000_000_000,
        "net_rx_bytes_per_sec": 1024,
        "net_tx_bytes_per_sec": 2048,
        "load_avg_1m": 1.2,
        "cpu_count": 4,
        "uptime_seconds": 3600.0,
    }
    payload.update(overrides)
    return payload


def _auth_header(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.mark.django_db
class TestHeartbeatMetrics:
    def test_heartbeat_persists_resource_sample(self, client):
        worker = Worker.objects.create(name="metrics-worker", hostname="metrics.vps.example.com")
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]
        agent = Agent.objects.get(id=agent_id)

        response = client.post(
            reverse("agent-heartbeat", kwargs={"agent_id": agent_id}),
            data={
                "installed_modules": [{"module_id": "docker"}],
                "docker_reachable": True,
                "metrics": _sample_metrics(),
            },
            content_type="application/json",
            **_auth_header(token),
        )

        assert response.status_code == 200
        samples = ResourceSample.objects.filter(agent=agent)
        assert samples.count() == 1
        sample = samples.get()
        assert sample.cpu_percent == 42.5
        assert sample.mem_percent == 55.0
        assert sample.net_tx_bytes_per_sec == 2048

    def test_heartbeat_without_metrics_does_not_create_sample(self, client):
        worker = Worker.objects.create(name="plain-worker", hostname="plain.vps.example.com")
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        response = client.post(
            reverse("agent-heartbeat", kwargs={"agent_id": agent_id}),
            data={"installed_modules": []},
            content_type="application/json",
            **_auth_header(token),
        )

        assert response.status_code == 200
        assert ResourceSample.objects.count() == 0

    def test_record_resource_sample_prunes_old_rows(self, settings):
        settings.RESOURCE_SAMPLE_RETENTION_SECONDS = 3600
        agent = Agent.objects.create(
            agent_type=AgentType.WORKER,
            token_prefix="agnt_prn",
            token_hash="c" * 64,
        )
        now = timezone.now()
        old_time = now - timedelta(seconds=7200)
        record_resource_sample(agent, _sample_metrics(cpu_percent=10.0), sampled_at=old_time)
        record_resource_sample(agent, _sample_metrics(cpu_percent=20.0), sampled_at=now)

        samples = list(ResourceSample.objects.filter(agent=agent).order_by("sampled_at"))
        assert len(samples) == 1
        assert samples[0].cpu_percent == 20.0
        assert resource_sample_retention_seconds() == 3600
