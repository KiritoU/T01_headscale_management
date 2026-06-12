from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from agents.models import AgentType
from workers.models import Worker, WorkerEnrollmentToken, WorkerStatus
from workers.services import (
    create_worker_enrollment_token,
    register_worker_from_token,
    revoke_worker_enrollment_token,
)


@pytest.fixture
def enrollment_credentials():
    return create_worker_enrollment_token("worker-enroll-1", expires_in_minutes=60)


@pytest.mark.django_db
class TestWorkerEnrollmentTokenService:
    def test_create_worker_enrollment_token_returns_raw_token(self):
        creds = create_worker_enrollment_token("worker-east", expires_in_minutes=30)

        assert creds.raw_token.startswith("wrk_")
        assert len(creds.raw_token[:8]) == 8
        worker = Worker.objects.get(id=creds.worker_id)
        assert worker.name == "worker-east"
        assert worker.status == WorkerStatus.PENDING

        token = WorkerEnrollmentToken.objects.get(worker=worker)
        assert token.max_uses == 1
        assert token.uses == 0
        assert token.revoked is False
        assert token.token_hash != creds.raw_token
        assert creds.install_url.startswith("/worker-agent.sh?token=")

    def test_create_rejects_duplicate_worker_name(self):
        create_worker_enrollment_token("worker-dup")

        with pytest.raises(ValueError, match="already exists"):
            create_worker_enrollment_token("worker-dup")

    def test_revoke_worker_enrollment_token(self, enrollment_credentials):
        token = WorkerEnrollmentToken.objects.get(worker_id=enrollment_credentials.worker_id)

        revoke_worker_enrollment_token(token)

        token.refresh_from_db()
        assert token.revoked is True

    def test_register_worker_from_token_creates_agent_and_links_worker(
        self, enrollment_credentials,
    ):
        worker, agent, agent_token = register_worker_from_token(
            enrollment_credentials.raw_token,
            hostname="vps-east-1",
        )

        assert worker.hostname == "vps-east-1"
        assert worker.agent_id == agent.id
        assert worker.credential_ref == enrollment_credentials.raw_token[:8]
        assert agent.agent_type == AgentType.WORKER
        assert agent_token.startswith("agnt_")

        token = WorkerEnrollmentToken.objects.get(worker=worker)
        assert token.uses == 1

    def test_register_rejects_revoked_token(self, enrollment_credentials):
        token = WorkerEnrollmentToken.objects.get(worker_id=enrollment_credentials.worker_id)
        revoke_worker_enrollment_token(token)

        with pytest.raises(ValueError, match="revoked"):
            register_worker_from_token(enrollment_credentials.raw_token)

    def test_register_rejects_expired_token(self):
        creds = create_worker_enrollment_token("worker-expired", expires_in_minutes=1)
        token = WorkerEnrollmentToken.objects.get(worker_id=creds.worker_id)
        WorkerEnrollmentToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        with pytest.raises(ValueError, match="expired"):
            register_worker_from_token(creds.raw_token)

    def test_register_rejects_exhausted_token(self, enrollment_credentials):
        register_worker_from_token(enrollment_credentials.raw_token)

        with pytest.raises(ValueError, match="exhausted"):
            register_worker_from_token(enrollment_credentials.raw_token)

    def test_register_rejects_already_enrolled_worker(self):
        creds = create_worker_enrollment_token("worker-re-enroll", max_uses=2)
        register_worker_from_token(creds.raw_token)

        with pytest.raises(ValueError, match="already enrolled"):
            register_worker_from_token(creds.raw_token)


@pytest.mark.django_db
class TestWorkerEnrollmentTokenAPI:
    def test_create_enrollment_token(self, client):
        response = client.post(
            reverse("worker-enrollment-token-create"),
            data={"name": "worker-api-1", "expires_in_minutes": 45},
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["token"].startswith("wrk_")
        assert body["data"]["name"] == "worker-api-1"
        assert body["data"]["worker_id"]
        assert body["data"]["expires_at"]
        assert WorkerEnrollmentToken.objects.filter(worker__name="worker-api-1").count() == 1

    def test_create_rejects_duplicate_name(self, client):
        client.post(
            reverse("worker-enrollment-token-create"),
            data={"name": "worker-dup-api"},
            content_type="application/json",
        )

        response = client.post(
            reverse("worker-enrollment-token-create"),
            data={"name": "worker-dup-api"},
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "already exists" in body["error"]


@pytest.mark.django_db
class TestWorkerEnrollmentRegisterAPI:
    def test_register_worker_with_enrollment_token(self, client, enrollment_credentials):
        response = client.post(
            reverse("agent-register"),
            data={
                "agent_type": AgentType.WORKER,
                "enrollment_token": enrollment_credentials.raw_token,
                "hostname": "enrolled-worker",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["token"].startswith("agnt_")

        worker = Worker.objects.get(id=enrollment_credentials.worker_id)
        assert str(worker.agent_id) == body["agent_id"]
        assert worker.hostname == "enrolled-worker"

    def test_register_rejects_gateway_token_for_worker(self, client, tenant):
        from gateways.services import create_enrollment_token

        gateway_creds = create_enrollment_token(tenant)

        response = client.post(
            reverse("agent-register"),
            data={
                "agent_type": AgentType.WORKER,
                "enrollment_token": gateway_creds.raw_token,
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_register_rejects_worker_token_for_gateway(self, client, enrollment_credentials):
        response = client.post(
            reverse("agent-register"),
            data={
                "agent_type": AgentType.GATEWAY,
                "enrollment_token": enrollment_credentials.raw_token,
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_register_rejects_worker_id_and_token_together(self, client, enrollment_credentials):
        response = client.post(
            reverse("agent-register"),
            data={
                "agent_type": AgentType.WORKER,
                "worker_id": enrollment_credentials.worker_id,
                "enrollment_token": enrollment_credentials.raw_token,
            },
            content_type="application/json",
        )

        assert response.status_code == 400


@pytest.fixture
def tenant(worker):
    from tenants.models import Tenant

    return Tenant.objects.create(
        slug="team-worker-enroll",
        headscale_host="hs.example.com",
        headplane_host="hp.example.com",
        db_name="hs_team_worker_enroll",
        worker=worker,
    )


@pytest.fixture
def worker():
    return Worker.objects.create(name="enroll-tenant-worker", hostname="tenant.vps.example.com")


@pytest.mark.django_db
class TestWorkerHeartbeatStatus:
    def test_heartbeat_sets_worker_online(self, client, enrollment_credentials):
        reg = client.post(
            reverse("agent-register"),
            data={
                "agent_type": AgentType.WORKER,
                "enrollment_token": enrollment_credentials.raw_token,
                "hostname": "hb-worker",
            },
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        worker = Worker.objects.get(id=enrollment_credentials.worker_id)
        assert worker.status == WorkerStatus.PENDING

        response = client.post(
            reverse("agent-heartbeat", kwargs={"agent_id": agent_id}),
            data={"docker_reachable": True},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == 200
        worker.refresh_from_db()
        assert worker.status == WorkerStatus.ONLINE
        assert worker.docker_reachable is True


def test_worker_agent_script_served(client):
    response = client.get(reverse("worker-agent-script"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/x-shellscript")
    body = response.content.decode()
    assert "#!/usr/bin/env bash" in body
    assert "worker agent installer" in body
    assert "enrollment_token" in body


def test_worker_agent_script_missing_returns_503(client):
    with patch.object(Path, "read_text", side_effect=OSError("missing")):
        response = client.get(reverse("worker-agent-script"))

    assert response.status_code == 503
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    assert "temporarily unavailable" in body.lower()
