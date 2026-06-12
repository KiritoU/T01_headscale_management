from __future__ import annotations

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentModule, CommandState
from agents.services import verify_agent_token
from tenants.models import Tenant
from workers.models import Worker, WorkerEnrollmentToken, WorkerStatus
from workers.services import (
    create_worker_enrollment_token,
    delete_worker,
    disconnect_worker,
    enqueue_worker_command,
    register_worker_from_token,
)


@pytest.fixture
def enrolled_worker():
    creds = create_worker_enrollment_token("disconnect-worker")
    worker, agent, raw_token = register_worker_from_token(creds.raw_token, hostname="vps-1")
    return worker, agent, raw_token


@pytest.mark.django_db
class TestRevokeAndDisconnectService:
    def test_disconnect_worker_revokes_token_and_enqueues_shutdown(self, enrolled_worker):
        worker, agent, raw_token = enrolled_worker

        result = disconnect_worker(worker)

        assert result.status == WorkerStatus.DISABLED
        assert verify_agent_token(raw_token) is None

        shutdown = AgentCommand.objects.get(agent=agent, command="shutdown")
        assert shutdown.state == CommandState.PENDING
        assert shutdown.payload == {}

    def test_disconnect_rejects_worker_without_agent(self):
        worker = Worker.objects.create(name="no-agent-worker")

        with pytest.raises(ValueError, match="no enrolled agent"):
            disconnect_worker(worker)

    def test_enqueue_worker_command_install_module(self, enrolled_worker):
        worker, agent, _ = enrolled_worker

        command = enqueue_worker_command(worker, "install_module", {"module": "docker"})

        assert command.agent_id == agent.id
        assert command.command == "install_module"
        assert command.payload == {"module": "docker"}

    def test_enqueue_rejects_unsupported_command(self, enrolled_worker):
        worker, _, _ = enrolled_worker

        with pytest.raises(ValueError, match="Unsupported worker command"):
            enqueue_worker_command(worker, "restart_universe")


@pytest.mark.django_db
class TestDeleteWorkerService:
    def test_delete_worker_removes_agent_and_enrollment_token(self, enrolled_worker):
        worker, agent, _ = enrolled_worker
        worker_id = worker.id
        agent_id = agent.id
        token_id = WorkerEnrollmentToken.objects.get(worker=worker).id

        delete_worker(worker)

        assert not Worker.objects.filter(id=worker_id).exists()
        assert not Agent.objects.filter(id=agent_id).exists()
        assert not AgentCommand.objects.filter(agent_id=agent_id).exists()
        assert not WorkerEnrollmentToken.objects.filter(id=token_id).exists()

    def test_delete_worker_rejects_when_tenants_assigned(self, enrolled_worker):
        worker, agent, _ = enrolled_worker
        Tenant.objects.create(
            slug="team-on-worker",
            headscale_host="hs.example.com",
            headplane_host="hp.example.com",
            db_name="hs_team_on_worker",
            worker=worker,
        )
        AgentCommand.objects.create(agent=agent, command="verify_tenant", payload={})
        AgentModule.objects.create(agent=agent, name="docker", installed_at=timezone.now())

        with pytest.raises(ValueError, match="assigned tenants"):
            delete_worker(worker)

        worker.refresh_from_db()
        assert Worker.objects.filter(id=worker.id).exists()
        assert Agent.objects.filter(id=agent.id).exists()


@pytest.mark.django_db
class TestWorkerDisconnectAPI:
    def test_disconnect_endpoint(self, client, enrolled_worker):
        worker, _, _ = enrolled_worker

        response = client.post(reverse("worker-disconnect", kwargs={"worker_id": worker.id}))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["status"] == WorkerStatus.DISABLED

        worker.refresh_from_db()
        assert worker.status == WorkerStatus.DISABLED
        assert AgentCommand.objects.filter(agent=worker.agent, command="shutdown").exists()

    def test_disconnect_rejects_worker_without_agent(self, client):
        worker = Worker.objects.create(name="api-no-agent")

        response = client.post(reverse("worker-disconnect", kwargs={"worker_id": worker.id}))

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "no enrolled agent" in body["error"]


@pytest.mark.django_db
class TestWorkerCommandsAPI:
    def test_enqueue_install_module(self, client, enrolled_worker):
        worker, agent, _ = enrolled_worker

        response = client.post(
            reverse("worker-commands", kwargs={"worker_id": worker.id}),
            data={"command": "install_module", "payload": {"module": "docker"}},
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["command"] == "install_module"
        assert body["data"]["payload"] == {"module": "docker"}

        cmd = AgentCommand.objects.get(id=body["data"]["id"])
        assert cmd.agent_id == agent.id
        assert cmd.state == CommandState.PENDING

    def test_enqueue_rejects_unsupported_command(self, client, enrolled_worker):
        worker, _, _ = enrolled_worker

        response = client.post(
            reverse("worker-commands", kwargs={"worker_id": worker.id}),
            data={"command": "restart_universe"},
            content_type="application/json",
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestWorkerDeleteAPI:
    def test_destroy_worker_without_tenants(self, client, enrolled_worker):
        worker, agent, _ = enrolled_worker
        worker_id = worker.id
        agent_id = agent.id

        response = client.delete(reverse("worker-detail", kwargs={"pk": worker_id}))

        assert response.status_code == 204
        assert not Worker.objects.filter(id=worker_id).exists()
        assert not Agent.objects.filter(id=agent_id).exists()

    def test_destroy_rejects_worker_with_tenants(self, client, enrolled_worker):
        worker, _, _ = enrolled_worker
        Tenant.objects.create(
            slug="team-block-delete",
            headscale_host="hs.example.com",
            headplane_host="hp.example.com",
            db_name="hs_team_block_delete",
            worker=worker,
        )

        response = client.delete(reverse("worker-detail", kwargs={"pk": worker.id}))

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "assigned tenants" in body["error"]
        assert Worker.objects.filter(id=worker.id).exists()

    def test_retrieve_includes_installed_modules(self, client, enrolled_worker):
        worker, agent, _ = enrolled_worker
        AgentModule.objects.create(agent=agent, name="docker", installed_at=timezone.now())

        response = client.get(reverse("worker-detail", kwargs={"pk": worker.id}))

        assert response.status_code == 200
        assert response.json()["installed_modules"] == ["docker"]

    def test_destroy_not_found(self, client):
        response = client.delete(reverse("worker-detail", kwargs={"pk": uuid.uuid4()}))

        assert response.status_code == 404
