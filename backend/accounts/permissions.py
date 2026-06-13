"""DRF permission classes for human operator RBAC."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import AccessLevel, Role, ScopeType
from accounts.scoping import effective_access


class IsAuthenticatedHuman(BasePermission):
    """Authenticated request user must be a human ``accounts.User`` (not an agent)."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(getattr(user, "is_authenticated", False) and hasattr(user, "role"))


class IsAdmin(BasePermission):
    """Only platform admins (``role=admin`` or superuser)."""

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_admin", False))


class DenyViewerOnWorkersGateways(BasePermission):
    """Viewers may only access tenant-scoped resources."""

    def has_permission(self, request, view) -> bool:
        if not IsAuthenticatedHuman().has_permission(request, view):
            return False
        if getattr(request.user, "role", None) != Role.VIEWER:
            return True
        scope_type = getattr(view, "scope_type", None)
        return scope_type not in {ScopeType.WORKER, ScopeType.GATEWAY}


class ScopedResourceAccess(BasePermission):
    """
    Object-level scoped access: SAFE methods require VIEW; mutating methods require EDIT.

    View must define ``scope_type`` and ``get_scope_id(obj)``.
    """

    def has_permission(self, request, view) -> bool:
        return IsAuthenticatedHuman().has_permission(request, view)

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if getattr(user, "is_admin", False):
            return True

        scope_type = getattr(view, "scope_type", None)
        get_scope_type = getattr(view, "get_scope_type", None)
        get_scope_id = getattr(view, "get_scope_id", None)
        if callable(get_scope_type):
            scope_type = get_scope_type(obj)
        if scope_type is None or get_scope_id is None:
            return False

        level = effective_access(user, scope_type, get_scope_id(obj))
        if level is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return level == AccessLevel.EDIT
