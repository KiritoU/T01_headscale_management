import pytest

from gateways.models import Gateway
from tenants.models import Tenant
from workers.models import Worker


@pytest.mark.django_db
def test_tenant_worker_gateway_relationships():
    worker = Worker.objects.create(name="worker-1", hostname="vps-1.example.com")
    tenant = Tenant.objects.create(
        slug="team-1",
        headscale_host="headscale-team-1.example.com",
        headplane_host="headplane-team-1.example.com",
        db_name="hs_team_1",
        worker=worker,
    )
    gateway = Gateway.objects.create(
        tenant=tenant,
        hostname="gw-site-a",
        custom_tags=["tag:gateway", "tag:site-hanoi"],
    )

    assert tenant.worker == worker
    assert list(worker.tenants.all()) == [tenant]
    assert list(tenant.gateways.all()) == [gateway]
    assert gateway.custom_tags == ["tag:gateway", "tag:site-hanoi"]
