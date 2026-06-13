"""Scope resolution for RBAC: effective access levels and queryset filters."""

from __future__ import annotations

import uuid

from django.db.models import Q

from accounts.models import AccessLevel, ResourceGrant, Role, ScopeType, User
from gateways.models import Gateway
from tenants.models import Tenant

_ACCESS_RANK = {
    AccessLevel.VIEW: 1,
    AccessLevel.EDIT: 2,
}


def _max_access_level(levels: list[str]) -> str | None:
    if not levels:
        return None
    return max(levels, key=lambda level: _ACCESS_RANK[level])


def _direct_grant_levels(
    user: User,
    *,
    scope_type: str,
    scope_id: uuid.UUID,
) -> list[str]:
    return list(
        ResourceGrant.objects.filter(
            user=user,
            scope_type=scope_type,
            scope_id=scope_id,
        ).values_list("access_level", flat=True)
    )


def _editor_inherited_levels(
    user: User,
    *,
    scope_type: str,
    scope_id: uuid.UUID,
) -> list[str]:
    levels: list[str] = []

    if scope_type == ScopeType.TENANT:
        worker_id = (
            Tenant.objects.filter(pk=scope_id).values_list("worker_id", flat=True).first()
        )
        if worker_id:
            levels.extend(_direct_grant_levels(user, scope_type=ScopeType.WORKER, scope_id=worker_id))

    elif scope_type == ScopeType.GATEWAY:
        gateway = (
            Gateway.objects.filter(pk=scope_id)
            .values("tenant_id", "tenant__worker_id")
            .first()
        )
        if gateway:
            levels.extend(
                _direct_grant_levels(
                    user,
                    scope_type=ScopeType.TENANT,
                    scope_id=gateway["tenant_id"],
                )
            )
            worker_id = gateway["tenant__worker_id"]
            if worker_id:
                levels.extend(
                    _direct_grant_levels(user, scope_type=ScopeType.WORKER, scope_id=worker_id)
                )

    return levels


def effective_access(
    user: User,
    scope_type: str,
    scope_id: uuid.UUID,
) -> str | None:
    """Return the highest access level for *scope_type*/*scope_id*, or None."""
    if user.is_admin:
        return AccessLevel.EDIT

    if user.role == Role.VIEWER:
        if scope_type != ScopeType.TENANT:
            return None
        levels = _direct_grant_levels(user, scope_type=scope_type, scope_id=scope_id)
        return AccessLevel.VIEW if AccessLevel.VIEW in levels else None

    if user.role != Role.EDITOR:
        return None

    levels = _direct_grant_levels(user, scope_type=scope_type, scope_id=scope_id)
    levels.extend(_editor_inherited_levels(user, scope_type=scope_type, scope_id=scope_id))
    return _max_access_level(levels)


def _grant_scope_ids(user: User, scope_type: str) -> list[uuid.UUID]:
    return list(
        ResourceGrant.objects.filter(user=user, scope_type=scope_type).values_list(
            "scope_id",
            flat=True,
        )
    )


def build_scope_q(user: User, scope_type: str) -> Q:
    """Build a ``Q`` object filtering querysets to resources the user may access."""
    if user.is_admin:
        return Q()

    if user.role == Role.VIEWER:
        if scope_type == ScopeType.TENANT:
            tenant_ids = _grant_scope_ids(user, ScopeType.TENANT)
            return Q(id__in=tenant_ids)
        return Q(pk__in=[])

    if user.role != Role.EDITOR:
        return Q(pk__in=[])

    if scope_type == ScopeType.WORKER:
        return Q(id__in=_grant_scope_ids(user, ScopeType.WORKER))

    if scope_type == ScopeType.TENANT:
        tenant_ids = _grant_scope_ids(user, ScopeType.TENANT)
        worker_ids = _grant_scope_ids(user, ScopeType.WORKER)
        return Q(id__in=tenant_ids) | Q(worker_id__in=worker_ids)

    if scope_type == ScopeType.GATEWAY:
        gateway_ids = _grant_scope_ids(user, ScopeType.GATEWAY)
        tenant_ids = _grant_scope_ids(user, ScopeType.TENANT)
        worker_ids = _grant_scope_ids(user, ScopeType.WORKER)
        return (
            Q(id__in=gateway_ids)
            | Q(tenant_id__in=tenant_ids)
            | Q(tenant__worker_id__in=worker_ids)
        )

    return Q(pk__in=[])
