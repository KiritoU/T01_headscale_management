import pytest
from django.urls import reverse

from core.models import PlatformSettings
from workers.models import Worker


@pytest.mark.django_db
class TestPlatformEdgeSettingsApi:
    def test_admin_can_read_and_update_edge_settings(self, client, admin_user):
        client.force_login(admin_user)
        PlatformSettings.objects.create(
            pk=1,
            acme_email="ops@example.com",
            cf_dns_api_token="cfat_test_token",
        )

        read = client.get(reverse("platform-edge-settings"))
        assert read.status_code == 200
        body = read.json()
        assert body["data"]["acme_email"] == "ops@example.com"
        assert body["data"]["cf_dns_api_token_configured"] is True

        patch = client.patch(
            reverse("platform-edge-settings"),
            {"acme_email": "tls@example.com", "cf_dns_api_token": "cfat_new"},
            content_type="application/json",
        )
        assert patch.status_code == 200
        assert patch.json()["data"]["acme_email"] == "tls@example.com"

        settings = PlatformSettings.load()
        assert settings.cf_dns_api_token == "cfat_new"

    def test_viewer_cannot_update_edge_settings(self, client, viewer_user):
        client.force_login(viewer_user)
        response = client.patch(
            reverse("platform-edge-settings"),
            {"acme_email": "blocked@example.com"},
            content_type="application/json",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestWorkerSharedEdgeField:
    def test_patch_worker_shared_edge(self, client, admin_user):
        worker = Worker.objects.create(name="edge-worker", hostname="edge.local")
        client.force_login(admin_user)

        response = client.patch(
            reverse("worker-detail", kwargs={"pk": worker.pk}),
            {"shared_edge_traefik": True},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["shared_edge_traefik"] is True

        worker.refresh_from_db()
        assert worker.shared_edge_traefik is True
