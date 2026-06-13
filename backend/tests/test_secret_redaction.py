import pytest

from accounts.models import AccessLevel, ResourceGrant, Role, ScopeType, User
from tenants.models import Tenant
from tenants.serializers import redact_secrets_from_mapping, user_can_view_tenant_secrets
from workers.models import Worker


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin-redact",
        password="test-pass-1234",
        role=Role.ADMIN,
    )


@pytest.fixture
def editor_user(db):
    return User.objects.create_user(
        username="editor-redact",
        password="test-pass-1234",
        role=Role.EDITOR,
    )


@pytest.mark.django_db
def test_redact_secrets_from_mapping_strips_without_tenant_context(editor_user):
    data = {
        "api_key": "secret-api",
        "auth_key": "secret-auth",
        "auth_key_gateway": "secret-gw",
        "auth_key_workspace": "secret-ws",
        "admin_user_id": "admin-1",
    }

    redacted = redact_secrets_from_mapping(data, editor_user)

    assert redacted == {"admin_user_id": "admin-1"}


@pytest.mark.django_db
def test_redact_secrets_from_mapping_strips_nested_bootstrap_keys(editor_user):
    data = {
        "exit_code": 0,
        "bootstrap": {
            "api_key": "secret-api",
            "auth_key_gateway": "secret-gw",
            "auth_key_workspace": "secret-ws",
            "auth_key": "secret-auth",
            "output_ref": "ref-1",
        },
        "bootstrap_info": {
            "api_key": "nested-api",
            "auth_key": "nested-auth",
            "slug": "team-1",
        },
    }

    redacted = redact_secrets_from_mapping(data, editor_user)

    assert redacted["bootstrap"] == {"output_ref": "ref-1"}
    assert redacted["bootstrap_info"] == {"slug": "team-1"}


@pytest.mark.django_db
def test_redact_secrets_from_mapping_preserves_secrets_for_admin(admin_user, editor_user):
    data = {
        "api_key": "secret-api",
        "bootstrap": {"auth_key_gateway": "secret-gw"},
    }

    assert redact_secrets_from_mapping(data, admin_user) == data
    assert redact_secrets_from_mapping(None, editor_user) is None


@pytest.mark.django_db
def test_viewer_with_tenant_grant_can_view_secrets(admin_user, viewer_user):
    worker = Worker.objects.create(name="worker-redact", hostname="redact.example.com")
    tenant = Tenant.objects.create(
        slug="team-redact",
        headscale_host="hs-redact.example.com",
        headplane_host="hp-redact.example.com",
        db_name="hs_redact",
        worker=worker,
        bootstrap_secrets={"api_key": "hskey-viewer"},
    )
    viewer = User.objects.create_user(
        username="viewer-redact",
        password="test-pass-1234",
        role=Role.VIEWER,
    )
    ResourceGrant.objects.create(
        user=viewer,
        scope_type=ScopeType.TENANT,
        scope_id=tenant.id,
        access_level=AccessLevel.VIEW,
        granted_by=admin_user,
    )

    assert user_can_view_tenant_secrets(viewer, tenant) is True
    data = {"api_key": "hskey-viewer", "admin_user_id": "1"}
    assert redact_secrets_from_mapping(data, viewer, tenant=tenant) == data
