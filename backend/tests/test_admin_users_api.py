import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import AccessLevel, ResourceGrant, Role, ScopeType, User
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin-api",
        password="test-pass-1234",
        role=Role.ADMIN,
    )


@pytest.fixture
def editor_user(db):
    return User.objects.create_user(
        username="editor-api",
        password="test-pass-1234",
        role=Role.EDITOR,
    )


@pytest.fixture
def worker(db):
    return Worker.objects.create(name="worker-admin", hostname="admin.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-admin",
        headscale_host="headscale-team-admin.example.com",
        headplane_host="headplane-team-admin.example.com",
        db_name="hs_team_admin",
        worker=worker,
    )


@pytest.mark.django_db
class TestAdminUserAccess:
    def test_list_users_requires_admin(self, api_client, editor_user):
        api_client.force_authenticate(user=editor_user)
        response = api_client.get(reverse("admin-user-list"))

        assert response.status_code == 403

    def test_admin_can_list_users(self, api_client, admin_user, editor_user):
        api_client.force_authenticate(user=admin_user)
        response = api_client.get(reverse("admin-user-list"))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        usernames = {user["username"] for user in body["data"]}
        assert "admin-api" in usernames
        assert "editor-api" in usernames


@pytest.mark.django_db
class TestAdminUserCrud:
    def test_create_user(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(
            reverse("admin-user-list"),
            {
                "username": "new-viewer",
                "password": "test-pass-1234",
                "role": Role.VIEWER,
                "email": "viewer@example.com",
            },
            format="json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["username"] == "new-viewer"
        assert body["data"]["role"] == Role.VIEWER
        assert User.objects.filter(username="new-viewer").exists()

    def test_create_user_requires_password(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(
            reverse("admin-user-list"),
            {"username": "no-password", "role": Role.VIEWER},
            format="json",
        )

        assert response.status_code == 400
        assert "password" in response.json()["error"].lower()

    def test_retrieve_user(self, api_client, admin_user, editor_user):
        api_client.force_authenticate(user=admin_user)
        response = api_client.get(
            reverse("admin-user-detail", kwargs={"user_id": editor_user.id}),
        )

        assert response.status_code == 200
        assert response.json()["data"]["username"] == "editor-api"

    def test_patch_user(self, api_client, admin_user, editor_user):
        api_client.force_authenticate(user=admin_user)
        response = api_client.patch(
            reverse("admin-user-detail", kwargs={"user_id": editor_user.id}),
            {"role": Role.VIEWER},
            format="json",
        )

        assert response.status_code == 200
        assert response.json()["data"]["role"] == Role.VIEWER
        editor_user.refresh_from_db()
        assert editor_user.role == Role.VIEWER

    def test_delete_user(self, api_client, admin_user, editor_user):
        api_client.force_authenticate(user=admin_user)
        user_id = editor_user.id
        response = api_client.delete(
            reverse("admin-user-detail", kwargs={"user_id": user_id}),
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert not User.objects.filter(id=user_id).exists()


@pytest.mark.django_db
class TestAdminUserGrants:
    def test_list_grants(self, api_client, admin_user, editor_user, tenant):
        ResourceGrant.objects.create(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        api_client.force_authenticate(user=admin_user)
        response = api_client.get(
            reverse("admin-user-grants", kwargs={"user_id": editor_user.id}),
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["scope_id"] == str(tenant.id)

    def test_create_grant(self, api_client, admin_user, editor_user, tenant):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(
            reverse("admin-user-grants", kwargs={"user_id": editor_user.id}),
            {
                "scope_type": ScopeType.TENANT,
                "scope_id": str(tenant.id),
                "access_level": AccessLevel.EDIT,
            },
            format="json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["access_level"] == AccessLevel.EDIT
        assert ResourceGrant.objects.filter(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
        ).exists()

    def test_create_grant_rejects_invalid_scope(self, api_client, admin_user, editor_user):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(
            reverse("admin-user-grants", kwargs={"user_id": editor_user.id}),
            {
                "scope_type": ScopeType.TENANT,
                "scope_id": "00000000-0000-0000-0000-000000000099",
                "access_level": AccessLevel.VIEW,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "not found" in response.json()["error"].lower()


@pytest.mark.django_db
class TestAdminGrantDelete:
    def test_delete_grant(self, api_client, admin_user, editor_user, tenant):
        grant = ResourceGrant.objects.create(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        api_client.force_authenticate(user=admin_user)
        response = api_client.delete(
            reverse("admin-grant-delete", kwargs={"grant_id": grant.id}),
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert not ResourceGrant.objects.filter(id=grant.id).exists()
