import uuid

from django.db import models


class WorkerStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ONLINE = "online", "Online"
    OFFLINE = "offline", "Offline"
    DISABLED = "disabled", "Disabled"


class Worker(models.Model):
    """VPS worker host that runs tenant stacks (stub — expanded in Phase 3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    hostname = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=WorkerStatus.choices,
        default=WorkerStatus.PENDING,
    )
    agent = models.OneToOneField(
        "agents.Agent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worker",
    )
    credential_ref = models.CharField(
        max_length=255,
        blank=True,
        help_text="Reference to rotatable agent credential (not plaintext).",
    )
    docker_reachable = models.BooleanField(default=False)
    shared_edge_traefik = models.BooleanField(
        default=False,
        help_text=(
            "Use the control plane Traefik for TLS instead of a per-worker Traefik "
            "instance (required when worker runs on the same host as the console)."
        ),
    )
    public_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Last public IP observed from the worker agent heartbeat.",
    )
    public_ip_override = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Manual override for DNS A records when auto-detection is wrong.",
    )
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WorkerEnrollmentToken(models.Model):
    """Single-use or limited token for worker agent enrollment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.OneToOneField(
        Worker,
        on_delete=models.CASCADE,
        related_name="enrollment_token",
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
        return f"{self.worker.name}:{self.prefix}"
