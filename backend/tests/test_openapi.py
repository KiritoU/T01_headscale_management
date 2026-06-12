from django.test import override_settings
from django.urls import reverse


@override_settings(DEBUG=True)
def test_openapi_schema_returns_200_when_debug(client):
    response = client.get(reverse("schema"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.oai.openapi")
