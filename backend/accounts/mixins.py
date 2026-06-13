"""Viewset mixins for scoped queryset filtering."""

from accounts.scoping import build_scope_q


class ScopedQuerysetMixin:
    """
    Filter list/detail querysets to granted (and inherited) resources.

    Viewsets using this mixin should set ``queryset = Model.objects.none()`` at
    class level and override ``get_queryset()`` to supply the base queryset
    before scoping, e.g.::

        queryset = Tenant.objects.none()

        def get_queryset(self):
            return self.filter_by_scope(Tenant.objects.all())
    """

    scope_type: str

    def filter_by_scope(self, queryset):
        user = self.request.user
        if not getattr(user, "is_authenticated", False):
            return queryset.none()
        return queryset.filter(build_scope_q(user, self.scope_type))
