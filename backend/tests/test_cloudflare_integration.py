from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from integrations.cloudflare import (
    CloudflareError,
    find_zone_id,
    upsert_a_record,
    verify_token,
)


class TestCloudflareClient:
    def test_verify_token_missing(self):
        status = verify_token("")
        assert status.valid is False
        assert status.status == "missing"

    @patch("integrations.cloudflare.httpx.Client")
    def test_verify_token_rejects_invalid_api_response(self, client_cls: MagicMock) -> None:
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
        client = client_cls.return_value.__enter__.return_value
        client.get.side_effect = [verify_response, zones_response]

        status = verify_token("cfat_test")
        assert status.valid is False
        assert status.status == "invalid"
        assert "Invalid request headers" in status.message

    @patch("integrations.cloudflare.httpx.Client")
    def test_verify_token_dns_scoped_falls_back_to_zone_access(self, client_cls: MagicMock) -> None:
        verify_response = MagicMock()
        verify_response.status_code = 401
        verify_response.json.return_value = {
            "success": False,
            "errors": [{"code": 1000, "message": "Invalid API Token"}],
        }
        zones_response = MagicMock()
        zones_response.status_code = 200
        zones_response.json.return_value = {
            "success": True,
            "result": [{"id": "zone123", "name": "ovncr.vn"}],
        }
        client = client_cls.return_value.__enter__.return_value
        client.get.side_effect = [verify_response, zones_response]

        status = verify_token("cfat_dns_scoped")
        assert status.valid is True
        assert status.status == "active"
        assert "ovncr.vn" in status.message

    @patch("integrations.cloudflare.httpx.Client")
    def test_verify_token_active(self, client_cls: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "success": True,
            "result": {"status": "active", "message": "ok"},
        }
        client_cls.return_value.__enter__.return_value.get.return_value = response

        status = verify_token("cfat_test")
        assert status.valid is True
        assert status.status == "active"

    @patch("integrations.cloudflare.httpx.Client")
    def test_find_zone_id_walks_parents(self, client_cls: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "success": True,
            "result": [{"id": "zone123", "name": "ovncr.vn"}],
        }
        client_cls.return_value.__enter__.return_value.get.return_value = response

        zone_id = find_zone_id("cfat_test", "headscale-team-1.network.ovncr.vn")
        assert zone_id == "zone123"

    @patch("integrations.cloudflare.httpx.Client")
    def test_upsert_a_record_creates_when_missing(self, client_cls: MagicMock) -> None:
        client = client_cls.return_value.__enter__.return_value
        zone_response = MagicMock()
        zone_response.status_code = 200
        zone_response.json.return_value = {
            "success": True,
            "result": [{"id": "zone123", "name": "ovncr.vn"}],
        }
        detail_response = MagicMock()
        detail_response.status_code = 200
        detail_response.json.return_value = {
            "success": True,
            "result": {"name": "ovncr.vn"},
        }
        list_response = MagicMock()
        list_response.status_code = 200
        list_response.json.return_value = {"success": True, "result": []}
        create_response = MagicMock()
        create_response.status_code = 200
        create_response.json.return_value = {
            "success": True,
            "result": {
                "id": "rec123",
                "name": "headscale-team-1.network.ovncr.vn",
                "content": "203.0.113.1",
            },
        }
        client.get.side_effect = [zone_response, detail_response, list_response]
        client.post.return_value = create_response

        result = upsert_a_record(
            "cfat_test",
            fqdn="headscale-team-1.network.ovncr.vn",
            ip="203.0.113.1",
        )
        assert result.record_id == "rec123"
        assert result.zone_id == "zone123"
        assert result.proxied is False

    @patch("integrations.cloudflare.httpx.Client")
    def test_find_zone_id_raises_when_missing(self, client_cls: MagicMock) -> None:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"success": True, "result": []}
        client_cls.return_value.__enter__.return_value.get.return_value = response

        with pytest.raises(CloudflareError):
            find_zone_id("cfat_test", "missing.example.com")
