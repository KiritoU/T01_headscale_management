import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import AccessLevel, ResourceGrant, Role, ScopeType, User


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def viewer_user(db):
    return User.objects.create_user(
        username="viewer-auth",
        password="test-pass-1234",
        role=Role.VIEWER,
    )


@pytest.fixture
def editor_user(db):
    return User.objects.create_user(
        username="editor-auth",
        password="test-pass-1234",
        role=Role.EDITOR,
    )


@pytest.mark.django_db
class TestAuthCsrf:
    def test_csrf_returns_token(self, api_client):
        response = api_client.get(reverse("auth-csrf"))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["csrf_token"]


@pytest.mark.django_db
class TestAuthLogin:
    def test_login_success(self, api_client, viewer_user):
        response = api_client.post(
            reverse("auth-login"),
            {"username": "viewer-auth", "password": "test-pass-1234"},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["username"] == "viewer-auth"
        assert body["data"]["role"] == Role.VIEWER

    def test_login_invalid_credentials_generic_error(self, api_client, viewer_user):
        response = api_client.post(
            reverse("auth-login"),
            {"username": "viewer-auth", "password": "wrong-password"},
            format="json",
        )

        assert response.status_code == 401
        body = response.json()
        assert body["success"] is False
        assert body["error"] == "Invalid username or password."

    def test_login_unknown_user_generic_error(self, api_client):
        response = api_client.post(
            reverse("auth-login"),
            {"username": "nobody", "password": "test-pass-1234"},
            format="json",
        )

        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "Invalid username or password."

    def test_login_inactive_user_generic_error(self, api_client, viewer_user):
        viewer_user.is_active = False
        viewer_user.save(update_fields=["is_active"])

        response = api_client.post(
            reverse("auth-login"),
            {"username": "viewer-auth", "password": "test-pass-1234"},
            format="json",
        )

        assert response.status_code == 401
        body = response.json()
        assert body["error"] == "Invalid username or password."


@pytest.mark.django_db
class TestAuthMe:
    def test_me_requires_authentication(self, api_client):
        response = api_client.get(reverse("auth-me"))

        assert response.status_code == 403

    def test_me_returns_user_and_grants(self, api_client, editor_user):
        scope_id = "00000000-0000-0000-0000-000000000010"
        ResourceGrant.objects.create(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=scope_id,
            access_level=AccessLevel.VIEW,
        )

        api_client.force_authenticate(user=editor_user)
        response = api_client.get(reverse("auth-me"))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["user"]["username"] == "editor-auth"
        assert len(body["data"]["grants"]) == 1
        assert body["data"]["grants"][0]["scope_id"] == scope_id


@pytest.mark.django_db
class TestAuthLogout:
    def test_logout_clears_session(self, api_client, viewer_user):
        api_client.force_authenticate(user=viewer_user)
        response = api_client.post(reverse("auth-logout"))

        assert response.status_code == 200
        assert response.json()["success"] is True


@pytest.mark.django_db
class TestAuthPasswordChange:
    def test_password_change_success(self, api_client, viewer_user):
        api_client.force_authenticate(user=viewer_user)
        response = api_client.post(
            reverse("auth-password"),
            {
                "current_password": "test-pass-1234",
                "new_password": "new-pass-5678",
            },
            format="json",
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

        viewer_user.refresh_from_db()
        assert viewer_user.check_password("new-pass-5678")

    def test_password_change_wrong_current_password(self, api_client, viewer_user):
        api_client.force_authenticate(user=viewer_user)
        response = api_client.post(
            reverse("auth-password"),
            {
                "current_password": "wrong-password",
                "new_password": "new-pass-5678",
            },
            format="json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "current password" in body["error"].lower()

    def test_password_change_preserves_session(self, api_client, viewer_user):
        login_response = api_client.post(
            reverse("auth-login"),
            {"username": "viewer-auth", "password": "test-pass-1234"},
            format="json",
        )
        assert login_response.status_code == 200

        change_response = api_client.post(
            reverse("auth-password"),
            {
                "current_password": "test-pass-1234",
                "new_password": "new-pass-5678",
            },
            format="json",
        )
        assert change_response.status_code == 200

        me_response = api_client.get(reverse("auth-me"))
        assert me_response.status_code == 200
        assert me_response.json()["data"]["user"]["username"] == "viewer-auth"
