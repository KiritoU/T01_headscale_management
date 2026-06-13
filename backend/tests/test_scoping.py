"""Tests for accounts.scoping — inheritance, viewer tenant-only, and queryset scoping."""

from __future__ import annotations

import uuid

import pytest

from accounts.models import AccessLevel, ResourceGrant, Role, ScopeType, User
from accounts.scoping import build_scope_q, effective_access
from gateways.models import Gateway
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin-user",
        password="test-pass-1234",
        role=Role.ADMIN,
    )


@pytest.fixture
def editor_user(db):
    return User.objects.create_user(
        username="editor-user",
        password="test-pass-1234",
        role=Role.EDITOR,
    )


@pytest.fixture
def viewer_user(db):
    return User.objects.create_user(
        username="viewer-user",
        password="test-pass-1234",
        role=Role.VIEWER,
    )


@pytest.fixture
def worker(db):
    return Worker.objects.create(name="worker-east", hostname="east.example.com")


@pytest.fixture
def other_worker(db):
    return Worker.objects.create(name="worker-west", hostname="west.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-alpha",
        headscale_host="hs-alpha.example.com",
        headplane_host="hp-alpha.example.com",
        db_name="hs_alpha",
        worker=worker,
    )


@pytest.fixture
def orphan_tenant(db):
    return Tenant.objects.create(
        slug="orphan-team",
        headscale_host="hs-orphan.example.com",
        headplane_host="hp-orphan.example.com",
        db_name="hs_orphan",
        worker=None,
    )


@pytest.fixture
def other_tenant(other_worker):
    return Tenant.objects.create(
        slug="team-beta",
        headscale_host="hs-beta.example.com",
        headplane_host="hp-beta.example.com",
        db_name="hs_beta",
        worker=other_worker,
    )


@pytest.fixture
def gateway(tenant):
    return Gateway.objects.create(tenant=tenant, hostname="gw-alpha-1")


@pytest.fixture
def other_gateway(other_tenant):
    return Gateway.objects.create(tenant=other_tenant, hostname="gw-beta-1")


def _grant(*, user, scope_type, scope_id, access_level, granted_by):
    return ResourceGrant.objects.create(
        user=user,
        scope_type=scope_type,
        scope_id=scope_id,
        access_level=access_level,
        granted_by=granted_by,
    )


@pytest.mark.django_db
class TestAdminAccess:
    def test_admin_has_edit_on_worker_tenant_gateway(
        self, admin_user, worker, tenant, gateway
    ):
        assert effective_access(admin_user, ScopeType.WORKER, worker.id) == AccessLevel.EDIT
        assert effective_access(admin_user, ScopeType.TENANT, tenant.id) == AccessLevel.EDIT
        assert effective_access(admin_user, ScopeType.GATEWAY, gateway.id) == AccessLevel.EDIT

    def test_admin_build_scope_q_matches_all(
        self, admin_user, worker, tenant, gateway, other_worker, other_tenant, other_gateway
    ):
        assert Worker.objects.filter(build_scope_q(admin_user, ScopeType.WORKER)).count() == 2
        assert Tenant.objects.filter(build_scope_q(admin_user, ScopeType.TENANT)).count() == 2
        assert Gateway.objects.filter(build_scope_q(admin_user, ScopeType.GATEWAY)).count() == 2


@pytest.mark.django_db
class TestEditorDownwardInheritance:
    def test_worker_grant_inherits_to_tenant_and_gateway(
        self, admin_user, editor_user, worker, tenant, gateway
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        assert effective_access(editor_user, ScopeType.WORKER, worker.id) == AccessLevel.EDIT
        assert effective_access(editor_user, ScopeType.TENANT, tenant.id) == AccessLevel.EDIT
        assert effective_access(editor_user, ScopeType.GATEWAY, gateway.id) == AccessLevel.EDIT

    def test_tenant_grant_inherits_to_gateway_not_worker(
        self, admin_user, editor_user, worker, tenant, gateway
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        assert effective_access(editor_user, ScopeType.TENANT, tenant.id) == AccessLevel.EDIT
        assert effective_access(editor_user, ScopeType.GATEWAY, gateway.id) == AccessLevel.EDIT
        assert effective_access(editor_user, ScopeType.WORKER, worker.id) is None

    def test_gateway_grant_only_affects_gateway(
        self, admin_user, editor_user, worker, tenant, gateway
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.GATEWAY,
            scope_id=gateway.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        assert effective_access(editor_user, ScopeType.GATEWAY, gateway.id) == AccessLevel.VIEW
        assert effective_access(editor_user, ScopeType.TENANT, tenant.id) is None
        assert effective_access(editor_user, ScopeType.WORKER, worker.id) is None

    def test_most_permissive_wins_view_worker_edit_tenant(
        self, admin_user, editor_user, worker, tenant, gateway
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )
        _grant(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        assert effective_access(editor_user, ScopeType.TENANT, tenant.id) == AccessLevel.EDIT
        assert effective_access(editor_user, ScopeType.GATEWAY, gateway.id) == AccessLevel.EDIT

    def test_most_permissive_wins_edit_worker_view_tenant(
        self, admin_user, editor_user, worker, tenant, gateway
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )
        _grant(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        assert effective_access(editor_user, ScopeType.TENANT, tenant.id) == AccessLevel.EDIT

    def test_orphan_tenant_requires_direct_grant(
        self, admin_user, editor_user, worker, orphan_tenant
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        assert effective_access(editor_user, ScopeType.TENANT, orphan_tenant.id) is None

        _grant(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=orphan_tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )
        assert effective_access(editor_user, ScopeType.TENANT, orphan_tenant.id) == AccessLevel.VIEW


@pytest.mark.django_db
class TestEditorBuildScopeQ:
    def test_worker_scope_q_limits_workers(
        self, admin_user, editor_user, worker, other_worker
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        visible = Worker.objects.filter(build_scope_q(editor_user, ScopeType.WORKER))
        assert list(visible.values_list("id", flat=True)) == [worker.id]

    def test_tenant_scope_q_includes_worker_children(
        self, admin_user, editor_user, worker, tenant, other_tenant
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        visible = Tenant.objects.filter(build_scope_q(editor_user, ScopeType.TENANT))
        assert list(visible.values_list("id", flat=True)) == [tenant.id]

    def test_gateway_scope_q_includes_tenant_and_worker_inheritance(
        self, admin_user, editor_user, worker, tenant, gateway, other_gateway
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        visible = Gateway.objects.filter(build_scope_q(editor_user, ScopeType.GATEWAY))
        assert list(visible.values_list("id", flat=True)) == [gateway.id]


@pytest.mark.django_db
class TestViewerTenantOnly:
    def test_viewer_tenant_view_grant(
        self, admin_user, viewer_user, tenant
    ):
        _grant(
            user=viewer_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        assert effective_access(viewer_user, ScopeType.TENANT, tenant.id) == AccessLevel.VIEW

    def test_viewer_denied_worker_and_gateway(
        self, admin_user, viewer_user, worker, tenant, gateway
    ):
        _grant(
            user=viewer_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        assert effective_access(viewer_user, ScopeType.WORKER, worker.id) is None
        assert effective_access(viewer_user, ScopeType.GATEWAY, gateway.id) is None

    def test_viewer_does_not_inherit_worker_grants(
        self, admin_user, viewer_user, worker, tenant, gateway
    ):
        """Even if a worker grant existed, viewers must not inherit downward."""
        ResourceGrant.objects.create(
            user=viewer_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        assert effective_access(viewer_user, ScopeType.TENANT, tenant.id) is None
        assert effective_access(viewer_user, ScopeType.GATEWAY, gateway.id) is None
        assert effective_access(viewer_user, ScopeType.WORKER, worker.id) is None

    def test_viewer_build_scope_q_tenant_only(
        self, admin_user, viewer_user, tenant, other_tenant, worker, gateway
    ):
        _grant(
            user=viewer_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        assert list(
            Tenant.objects.filter(build_scope_q(viewer_user, ScopeType.TENANT)).values_list(
                "id", flat=True
            )
        ) == [tenant.id]
        assert Worker.objects.filter(build_scope_q(viewer_user, ScopeType.WORKER)).count() == 0
        assert Gateway.objects.filter(build_scope_q(viewer_user, ScopeType.GATEWAY)).count() == 0


@pytest.mark.django_db
class TestCrossScope404Logic:
    """Scoped querysets must exclude out-of-scope resources (404, not 403)."""

    def test_editor_cannot_see_other_worker_via_scope_q(
        self, admin_user, editor_user, worker, other_worker
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.WORKER,
            scope_id=worker.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        q = build_scope_q(editor_user, ScopeType.WORKER)
        assert Worker.objects.filter(q, pk=other_worker.id).exists() is False
        assert Worker.objects.filter(q, pk=worker.id).exists() is True

    def test_editor_cannot_see_other_tenant_via_scope_q(
        self, admin_user, editor_user, tenant, other_tenant
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )

        q = build_scope_q(editor_user, ScopeType.TENANT)
        assert Tenant.objects.filter(q, pk=other_tenant.id).exists() is False
        assert Tenant.objects.filter(q, pk=tenant.id).exists() is True

    def test_editor_cannot_see_other_gateway_via_scope_q(
        self, admin_user, editor_user, gateway, other_gateway
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.GATEWAY,
            scope_id=gateway.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        q = build_scope_q(editor_user, ScopeType.GATEWAY)
        assert Gateway.objects.filter(q, pk=other_gateway.id).exists() is False
        assert Gateway.objects.filter(q, pk=gateway.id).exists() is True

    def test_random_uuid_not_in_scoped_queryset(
        self, admin_user, editor_user, tenant
    ):
        _grant(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        random_id = uuid.uuid4()
        q = build_scope_q(editor_user, ScopeType.TENANT)
        assert Tenant.objects.filter(q, pk=random_id).exists() is False

    def test_ungranted_user_gets_empty_scope_q(self, editor_user, worker, tenant, gateway):
        empty_worker_q = build_scope_q(editor_user, ScopeType.WORKER)
        empty_tenant_q = build_scope_q(editor_user, ScopeType.TENANT)
        empty_gateway_q = build_scope_q(editor_user, ScopeType.GATEWAY)

        assert Worker.objects.filter(empty_worker_q).count() == 0
        assert Tenant.objects.filter(empty_tenant_q).count() == 0
        assert Gateway.objects.filter(empty_gateway_q).count() == 0
