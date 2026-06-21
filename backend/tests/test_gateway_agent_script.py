from pathlib import Path

from django.urls import reverse


def test_gateway_agent_script_served(client):
    response = client.get(reverse("gateway-agent-script"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/x-shellscript")
    body = response.content.decode()
    assert "#!/usr/bin/env bash" in body
    assert "gateway agent installer" in body
    assert "install-gateway-agent-systemd.sh" in body
    assert "POLL_INTERVAL" in body


def test_gateway_agent_script_injects_token_and_control_plane_url(client, settings):
    settings.PUBLIC_BASE_URL = "https://control.example.com"
    response = client.get(
        reverse("gateway-agent-script"),
        {"token": "enrl_testtoken123"},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "# __INJECTED_BY_CONTROL_PLANE__" in body
    assert 'CONTROL_PLANE_URL="https://control.example.com"' in body
    assert 'ENROLL_TOKEN="enrl_testtoken123"' in body


def test_worker_agent_script_injects_token(client, settings):
    settings.PUBLIC_BASE_URL = "http://127.0.0.1:8081"
    response = client.get(
        reverse("worker-agent-script"),
        {"token": "wrk_testtoken456"},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert 'ENROLL_TOKEN="wrk_testtoken456"' in body
    assert 'CONTROL_PLANE_URL="http://127.0.0.1:8081"' in body


def test_agent_script_rejects_invalid_token(client):
    response = client.get(
        reverse("gateway-agent-script"),
        {"token": "bad token with spaces"},
    )
    assert response.status_code == 400


def test_gateway_agent_script_missing_returns_503(client):
    from unittest.mock import patch

    with patch.object(Path, "read_text", side_effect=OSError("missing")):
        response = client.get(reverse("gateway-agent-script"))

    assert response.status_code == 503
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    assert "temporarily unavailable" in body.lower()


def test_gateway_agent_service_template_has_boot_and_env_paths():
    template = (
        Path(__file__).resolve().parents[1] / "scripts" / "gateway-agent.service.template"
    ).read_text(encoding="utf-8")

    assert "WantedBy=multi-user.target" in template
    assert "EnvironmentFile=@ENV_FILE@" in template
    assert "PYTHONPATH=@INSTALL_DIR@" in template
    assert "Restart=always" in template


def test_install_gateway_agent_systemd_script_exists():
    script = Path(__file__).resolve().parents[1] / "scripts" / "install-gateway-agent-systemd.sh"
    body = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "systemctl enable" in body
    assert "systemctl restart" in body
