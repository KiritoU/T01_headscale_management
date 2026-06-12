import uuid

from django.db import models


class GatewayStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ENROLLED = "enrolled", "Enrolled"
    ONLINE = "online", "Online"
    OFFLINE = "offline", "Offline"
    DISABLED = "disabled", "Disabled"


class EnrollmentToken(models.Model):
    """Tenant-scoped token for gateway agent enrollment (single-use or limited)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="enrollment_tokens",
    )
    token_hash = models.CharField(max_length=64)
    prefix = models.CharField(max_length=8, db_index=True)
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tenant.slug}:{self.prefix}"


class Gateway(models.Model):
    """Subnet router gateway agent (stub — expanded in Phase 6)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="gateways",
    )
    hostname = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=GatewayStatus.choices,
        default=GatewayStatus.PENDING,
    )
    agent = models.OneToOneField(
        "agents.Agent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gateway",
    )
    enrollment_token_ref = models.CharField(max_length=255, blank=True)
    custom_tags = models.JSONField(default=list, blank=True)
    tailscale_node_id = models.CharField(max_length=64, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["hostname", "id"]

    def __str__(self) -> str:
        label = self.hostname or str(self.id)
        return f"{self.tenant.slug}:{label}"
