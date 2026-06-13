import uuid

from accounts.models import AccessLevel, ResourceGrant, Role, ScopeType, User
from gateways.models import Gateway
from tenants.models import Tenant
from workers.models import Worker


class GrantValidationError(ValueError):
    """Raised when a grant violates role or scope rules."""


def validate_scope_exists(scope_type: str, scope_id: uuid.UUID) -> None:
    if scope_type == ScopeType.WORKER:
        if not Worker.objects.filter(id=scope_id).exists():
            raise GrantValidationError("Worker not found")
    elif scope_type == ScopeType.TENANT:
        if not Tenant.objects.filter(id=scope_id).exists():
            raise GrantValidationError("Tenant not found")
    elif scope_type == ScopeType.GATEWAY:
        if not Gateway.objects.filter(id=scope_id).exists():
            raise GrantValidationError("Gateway not found")
    else:
        raise GrantValidationError(f"Invalid scope_type: {scope_type}")


def validate_grant_for_user(
    *,
    user: User,
    scope_type: str,
    scope_id: uuid.UUID,
    access_level: str,
    granted_by: User,
) -> None:
    if not granted_by.is_admin:
        raise GrantValidationError("Only admins can issue grants")

    if user.is_admin:
        raise GrantValidationError("Admins do not need grants")

    if user.role == Role.VIEWER:
        if scope_type != ScopeType.TENANT:
            raise GrantValidationError("Viewers can only receive tenant grants")
        if access_level != AccessLevel.VIEW:
            raise GrantValidationError("Viewers can only receive view access")

    if user.role == Role.EDITOR and access_level not in AccessLevel.values:
        raise GrantValidationError(f"Invalid access level: {access_level}")

    validate_scope_exists(scope_type, scope_id)


def create_grant(
    *,
    user: User,
    scope_type: str,
    scope_id: uuid.UUID,
    access_level: str,
    granted_by: User,
) -> ResourceGrant:
    validate_grant_for_user(
        user=user,
        scope_type=scope_type,
        scope_id=scope_id,
        access_level=access_level,
        granted_by=granted_by,
    )
    grant, _created = ResourceGrant.objects.update_or_create(
        user=user,
        scope_type=scope_type,
        scope_id=scope_id,
        defaults={
            "access_level": access_level,
            "granted_by": granted_by,
        },
    )
    return grant
