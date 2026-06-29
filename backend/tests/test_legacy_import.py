import uuid

import pytest
from django.urls import reverse

from tenants.legacy import import_legacy_tenant, legacy_tenant_metadata
from tenants.models import Tenant
from workers.models import Worker


def test_legacy_tenant_metadata_team_1():
    metadata = legacy_tenant_metadata(suffix="team", number=1, base_domain="example.com")

    assert metadata == {
        "slug": "team-1",
        "db_name": "hs_team_1",
        "headscale_host": "headscale-team-1.example.com",
        "headplane_host": "headplane-team-1.example.com",
        "desired_config": {
            "production": False,
            "base_domain": "example.com",
            "download_host": "download.example.com",
            "dns": {
                "magic_dns_base": "tailnet-team-1.example.com",
            },
        },
    }


def test_legacy_tenant_metadata_without_number():
    metadata = legacy_tenant_metadata(suffix="soc", number=None, base_domain="example.com")

    assert metadata["slug"] == "soc"
    assert metadata["db_name"] == "hs_soc"
    assert metadata["headscale_host"] == "headscale-soc.example.com"
    assert metadata["headplane_host"] == "headplane-soc.example.com"
    assert metadata["desired_config"]["dns"]["magic_dns_base"] == "tailnet-soc.example.com"


def test_legacy_tenant_metadata_team_3():
    metadata = legacy_tenant_metadata(suffix="team", number=3, base_domain="vpn.example.net")

    assert metadata["slug"] == "team-3"
    assert metadata["db_name"] == "hs_team_3"
    assert metadata["headscale_host"] == "headscale-team-3.vpn.example.net"
    assert metadata["headplane_host"] == "headplane-team-3.vpn.example.net"
    assert metadata["desired_config"]["dns"]["magic_dns_base"] == "tailnet-team-3.vpn.example.net"


@pytest.mark.django_db
def test_import_legacy_tenant_creates_record():
    tenant = import_legacy_tenant(suffix="team", number=2, base_domain="example.com")

    assert tenant.slug == "team-2"
    assert tenant.db_name == "hs_team_2"
    assert tenant.headscale_host == "headscale-team-2.example.com"
    assert tenant.headplane_host == "headplane-team-2.example.com"
    assert tenant.desired_config["dns"]["magic_dns_base"] == "tailnet-team-2.example.com"
    assert tenant.worker is None
    assert Tenant.objects.filter(slug="team-2").exists()


@pytest.mark.django_db
def test_import_legacy_tenant_with_worker():
    worker = Worker.objects.create(name="worker-legacy", hostname="vps.example.com")

    tenant = import_legacy_tenant(
        suffix="team",
        number=4,
        base_domain="example.com",
        worker_id=worker.id,
    )

    assert tenant.worker == worker
    assert list(worker.tenants.all()) == [tenant]


@pytest.mark.django_db
def test_import_legacy_tenant_api(client):
    response = client.post(
        reverse("tenant-import-legacy"),
        data={
            "suffix": "team",
            "number": 5,
            "base_domain": "example.com",
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "team-5"
    assert data["db_name"] == "hs_team_5"
    assert data["headscale_host"] == "headscale-team-5.example.com"
    assert data["headplane_host"] == "headplane-team-5.example.com"
    assert data["desired_config"]["dns"]["magic_dns_base"] == "tailnet-team-5.example.com"
    assert data["worker"] is None
    assert Tenant.objects.filter(slug="team-5").exists()


@pytest.mark.django_db
def test_import_legacy_tenant_api_with_worker(client):
    worker = Worker.objects.create(name="worker-api", hostname="api.example.com")

    response = client.post(
        reverse("tenant-import-legacy"),
        data={
            "suffix": "team",
            "number": 6,
            "base_domain": "example.com",
            "worker_id": str(worker.id),
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["worker"] == str(worker.id)


@pytest.mark.django_db
def test_import_legacy_tenant_api_rejects_unknown_worker(client):
    response = client.post(
        reverse("tenant-import-legacy"),
        data={
            "suffix": "team",
            "number": 7,
            "base_domain": "example.com",
            "worker_id": str(uuid.uuid4()),
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert "worker_id" in body["error"]
