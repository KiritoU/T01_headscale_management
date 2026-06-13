import pytest
from django.db import IntegrityError

from accounts.models import AccessLevel, ResourceGrant, Role, ScopeType, User
from accounts.services.grants import GrantValidationError, validate_grant_for_user


@pytest.mark.django_db
def test_user_defaults_to_viewer_role():
    user = User.objects.create_user(username="viewer1", password="test-pass-1234")
    assert user.role == Role.VIEWER
    assert user.is_admin is False


@pytest.mark.django_db
def test_admin_user_has_admin_flag():
    user = User.objects.create_user(
        username="admin1",
        password="test-pass-1234",
        role=Role.ADMIN,
    )
    assert user.is_admin is True


@pytest.mark.django_db
def test_resource_grant_unique_per_user_scope():
    admin = User.objects.create_user(username="admin1", password="test-pass-1234", role=Role.ADMIN)
    editor = User.objects.create_user(username="editor1", password="test-pass-1234", role=Role.EDITOR)
    scope_id = "00000000-0000-0000-0000-000000000001"

    ResourceGrant.objects.create(
        user=editor,
        scope_type=ScopeType.TENANT,
        scope_id=scope_id,
        access_level=AccessLevel.VIEW,
        granted_by=admin,
    )

    with pytest.raises(IntegrityError):
        ResourceGrant.objects.create(
            user=editor,
            scope_type=ScopeType.TENANT,
            scope_id=scope_id,
            access_level=AccessLevel.EDIT,
            granted_by=admin,
        )


@pytest.mark.django_db
def test_validate_grant_rejects_viewer_non_tenant_scope():
    admin = User.objects.create_user(username="admin1", password="test-pass-1234", role=Role.ADMIN)
    viewer = User.objects.create_user(username="viewer1", password="test-pass-1234", role=Role.VIEWER)
    scope_id = "00000000-0000-0000-0000-000000000002"

    with pytest.raises(GrantValidationError):
        validate_grant_for_user(
            user=viewer,
            scope_type=ScopeType.WORKER,
            scope_id=scope_id,
            access_level=AccessLevel.VIEW,
            granted_by=admin,
        )


@pytest.mark.django_db
def test_validate_grant_rejects_viewer_edit_level():
    admin = User.objects.create_user(username="admin1", password="test-pass-1234", role=Role.ADMIN)
    viewer = User.objects.create_user(username="viewer1", password="test-pass-1234", role=Role.VIEWER)
    scope_id = "00000000-0000-0000-0000-000000000003"

    with pytest.raises(GrantValidationError):
        validate_grant_for_user(
            user=viewer,
            scope_type=ScopeType.TENANT,
            scope_id=scope_id,
            access_level=AccessLevel.EDIT,
            granted_by=admin,
        )
