from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse

from agents.models import Agent, AgentType
from core.models import PlatformSettings
from dns.models import DnsRecordPurpose, ManagedDnsRecord
from dns.services import ensure_download_dns, ensure_tenant_dns, remove_tenant_dns
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def worker_agent(db):
    worker = Worker.objects.create(
        name="dns-worker",
        hostname="dns.vps.example.com",
        public_ip="203.0.113.10",
    )
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_dns",
        token_hash="b" * 64,
    )
    worker.agent = agent
    worker.save(update_fields=["agent"])
    return worker


@pytest.fixture
def production_tenant(worker_agent):
    return Tenant.objects.create(
        slug="soc-1",
        headscale_host="headscale-soc-1.soc.ovncr.vn",
        headplane_host="headplane-soc-1.soc.ovncr.vn",
        db_name="hs_soc_1",
        worker=worker_agent,
        desired_config={"production": True, "base_domain": "soc.ovncr.vn"},
    )


@pytest.mark.django_db
class TestDnsServices:
    @patch("dns.services.upsert_a_record")
    def test_ensure_tenant_dns_creates_two_records(
        self,
        upsert_mock,
        production_tenant,
    ) -> None:
        PlatformSettings.objects.create(
            pk=1,
            cf_dns_api_token="cfat_test",
        )
        upsert_mock.side_effect = [
            type(
                "Result",
                (),
                {
                    "fqdn": production_tenant.headscale_host,
                    "zone_id": "zone1",
                    "record_id": "rec1",
                    "target_ip": "203.0.113.10",
                    "proxied": False,
                },
            )(),
            type(
                "Result",
                (),
                {
                    "fqdn": production_tenant.headplane_host,
                    "zone_id": "zone1",
                    "record_id": "rec2",
                    "target_ip": "203.0.113.10",
                    "proxied": False,
                },
            )(),
        ]

        records = ensure_tenant_dns(production_tenant)
        assert len(records) == 2
        assert ManagedDnsRecord.objects.filter(tenant=production_tenant).count() == 2
        assert upsert_mock.call_count == 2

    @patch("dns.services.delete_a_record")
    def test_remove_tenant_dns_deletes_managed_records(
        self,
        delete_mock,
        production_tenant,
    ) -> None:
        PlatformSettings.objects.create(pk=1, cf_dns_api_token="cfat_test")
        ManagedDnsRecord.objects.create(
            fqdn=production_tenant.headscale_host,
            zone_id="zone1",
            cf_record_id="rec1",
            target_ip="203.0.113.10",
            purpose=DnsRecordPurpose.TENANT_HEADSCALE,
            tenant=production_tenant,
        )

        remove_tenant_dns(production_tenant)
        delete_mock.assert_called_once()
        assert ManagedDnsRecord.objects.filter(tenant=production_tenant).count() == 0

    @patch("dns.services.upsert_a_record")
    def test_ensure_download_dns(self, upsert_mock) -> None:
        settings = PlatformSettings.objects.create(
            pk=1,
            cf_dns_api_token="cfat_test",
            download_host="download.ovncr.vn",
            download_target_ip="203.0.113.20",
        )
        upsert_mock.return_value = type(
            "Result",
            (),
            {
                "fqdn": "download.ovncr.vn",
                "zone_id": "zone1",
                "record_id": "rec_dl",
                "target_ip": "203.0.113.20",
                "proxied": False,
            },
        )()

        record = ensure_download_dns(settings)
        assert record.purpose == DnsRecordPurpose.CONSOLE_DOWNLOAD
        assert record.cf_record_id == "rec_dl"


@pytest.mark.django_db
class TestTenantScriptEndpoint:
    def test_script_endpoint_returns_linux_script(self, client, production_tenant):
        response = client.get(
            reverse(
                "tenant-script",
                kwargs={"slug": production_tenant.slug, "script_name": "linux.sh"},
            ),
        )
        assert response.status_code == 200
        assert production_tenant.headscale_host in response.content.decode()

    def test_script_endpoint_404_for_unknown_script(self, client, production_tenant):
        response = client.get(
            reverse(
                "tenant-script",
                kwargs={"slug": production_tenant.slug, "script_name": "missing.sh"},
            ),
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestConsoleSettingsApi:
    def test_admin_can_read_console_settings(self, client, admin_user):
        PlatformSettings.objects.create(
            pk=1,
            acme_email="ops@example.com",
            cf_dns_api_token="cfat_test",
            download_host="download.ovncr.vn",
            download_target_ip="203.0.113.20",
        )
        client.force_login(admin_user)
        response = client.get(reverse("platform-console-settings"))
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["download_host"] == "download.ovncr.vn"
        assert data["cf_dns_api_token_configured"] is True
        assert "cf_dns_api_token" not in data

    @patch("core.views.verify_token")
    def test_verify_cloudflare_endpoint(self, verify_mock, client, admin_user):
        PlatformSettings.objects.create(pk=1, cf_dns_api_token="cfat_test")
        verify_mock.return_value = type(
            "Status",
            (),
            {"valid": True, "status": "active", "message": "ok"},
        )()
        client.force_login(admin_user)
        response = client.post(reverse("platform-verify-cloudflare"))
        assert response.status_code == 200
        assert response.json()["data"]["valid"] is True

    @patch("integrations.cloudflare.httpx.Client")
    def test_verify_cloudflare_endpoint_returns_json_for_invalid_token(
        self,
        client_cls: MagicMock,
        client,
        admin_user,
    ):
        PlatformSettings.objects.create(pk=1, cf_dns_api_token="cfat_invalid")
        verify_response = MagicMock()
        verify_response.status_code = 401
        verify_response.json.return_value = {
            "success": False,
            "errors": [{"code": 1000, "message": "Invalid API Token"}],
        }
        zones_response = MagicMock()
        zones_response.status_code = 400
        zones_response.json.return_value = {
            "success": False,
            "errors": [{"message": "Invalid request headers"}],
        }
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.side_effect = [verify_response, zones_response]
        client.force_login(admin_user)
        response = client.post(reverse("platform-verify-cloudflare"))
        assert response.status_code == 400
        body = response.json()
        assert body["success"] is True
        assert body["data"]["valid"] is False
        assert "Invalid request headers" in body["data"]["message"]
        assert body["data"]["token_source"] == "database"
