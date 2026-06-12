import uuid

import pytest
from django.urls import reverse

from workers.models import Worker, WorkerStatus


@pytest.fixture
def worker_payload():
    return {
        "name": "worker-east",
        "hostname": "east.vps.example.com",
        "status": WorkerStatus.PENDING,
        "credential_ref": "vault://workers/east",
        "docker_reachable": False,
    }


@pytest.fixture
def worker(worker_payload):
    return Worker.objects.create(**worker_payload)


@pytest.mark.django_db
class TestWorkerListCreate:
    def test_list_workers_empty(self, client):
        response = client.get(reverse("worker-list"))

        assert response.status_code == 200
        assert response.json() == []

    def test_create_worker(self, client, worker_payload):
        response = client.post(
            reverse("worker-list"),
            data=worker_payload,
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == worker_payload["name"]
        assert data["hostname"] == worker_payload["hostname"]
        assert Worker.objects.filter(name=worker_payload["name"]).exists()


@pytest.mark.django_db
class TestWorkerDetail:
    def test_retrieve_worker(self, client, worker):
        response = client.get(reverse("worker-detail", kwargs={"pk": worker.id}))

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == worker.name
        assert data["status"] == WorkerStatus.PENDING

    def test_update_worker(self, client, worker):
        response = client.patch(
            reverse("worker-detail", kwargs={"pk": worker.id}),
            data={"status": WorkerStatus.ONLINE, "docker_reachable": True},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == WorkerStatus.ONLINE
        assert data["docker_reachable"] is True

    def test_retrieve_not_found_returns_envelope(self, client):
        response = client.get(reverse("worker-detail", kwargs={"pk": uuid.uuid4()}))

        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert body["error"]
