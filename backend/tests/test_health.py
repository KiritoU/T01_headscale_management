import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_returns_ok_envelope(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["service"] == "headscale-management"
    assert "version" in payload["data"]
