import pytest
from django.urls import reverse

from agents.models import Agent, AgentType
from workers.models import Worker, WorkerStatus


@pytest.mark.django_db
class TestHeartbeatPublicIp:
    def test_heartbeat_persists_client_ip_on_worker(self, client):
        worker = Worker.objects.create(name="hb-worker", hostname="hb.vps.example.com")
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        response = client.post(
            reverse("agent-heartbeat", kwargs={"agent_id": agent_id}),
            data={"docker_reachable": True, "installed_modules": []},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_FORWARDED_FOR="203.0.113.55, 10.0.0.1",
        )
        assert response.status_code == 200
        worker.refresh_from_db()
        assert worker.public_ip == "203.0.113.55"
        assert worker.status == WorkerStatus.ONLINE
