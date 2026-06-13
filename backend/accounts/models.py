import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"


class ScopeType(models.TextChoices):
    WORKER = "worker", "Worker"
    TENANT = "tenant", "Tenant"
    GATEWAY = "gateway", "Gateway"


class AccessLevel(models.TextChoices):
    VIEW = "view", "View"
    EDIT = "edit", "Edit"


class User(AbstractUser):
    """Human operator for the control plane UI and API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN or self.is_superuser


class ResourceGrant(models.Model):
    """Scoped permission for one user over one worker, tenant, or gateway."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="grants")
    scope_type = models.CharField(max_length=16, choices=ScopeType.choices)
    scope_id = models.UUIDField()
    access_level = models.CharField(max_length=8, choices=AccessLevel.choices)
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grants_issued",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "scope_type", "scope_id"],
                name="accounts_unique_user_scope",
            )
        ]
        indexes = [
            models.Index(fields=["user", "scope_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username}:{self.scope_type}:{self.scope_id}:{self.access_level}"
