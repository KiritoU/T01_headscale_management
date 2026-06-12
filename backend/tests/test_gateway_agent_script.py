from pathlib import Path
from unittest.mock import patch

from django.urls import reverse


def test_gateway_agent_script_served(client):
    response = client.get(reverse("gateway-agent-script"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/x-shellscript")
    body = response.content.decode()
    assert "#!/usr/bin/env bash" in body
    assert "gateway agent installer" in body


def test_gateway_agent_script_missing_returns_503(client):
    with patch.object(Path, "read_text", side_effect=OSError("missing")):
        response = client.get(reverse("gateway-agent-script"))

    assert response.status_code == 503
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    assert "temporarily unavailable" in body.lower()
