import re
import uuid

from django.db import models

_ERROR_MESSAGE_MAX_LENGTH = 500
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_error_message(value: str) -> str:
    cleaned = _CONTROL_CHAR_PATTERN.sub("", value.strip())
    return cleaned[:_ERROR_MESSAGE_MAX_LENGTH]


class BootstrapStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROVISIONING = "provisioning", "Provisioning"
    BOOTSTRAPPED = "bootstrapped", "Bootstrapped"
    FAILED = "failed", "Failed"


class RuntimeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROVISIONING = "provisioning", "Provisioning"
    RUNNING = "running", "Running"
    STOPPED = "stopped", "Stopped"
    FAILED = "failed", "Failed"


class Tenant(models.Model):
    """Headscale + Headplane tailnet instance (stub — expanded in Phase 2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=64, unique=True)
    headscale_host = models.CharField(max_length=255)
    headplane_host = models.CharField(max_length=255)
    db_name = models.CharField(max_length=128)
    worker = models.ForeignKey(
        "workers.Worker",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenants",
    )
    bootstrap_status = models.CharField(
        max_length=16,
        choices=BootstrapStatus.choices,
        default=BootstrapStatus.PENDING,
    )
    runtime_status = models.CharField(
        max_length=16,
        choices=RuntimeStatus.choices,
        default=RuntimeStatus.PENDING,
    )
    bootstrap_output_ref = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Reference to bootstrap output artifact (not raw keys).",
    )
    bootstrap_secrets = models.JSONField(
        default=dict,
        blank=True,
        help_text="Bootstrap credentials synced from worker after bootstrap_tenant ack.",
    )
    desired_config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.slug


class TenantHealth(models.Model):
    """Point-in-time health probe result for a tenant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="health_checks",
    )
    source_command = models.OneToOneField(
        "agents.AgentCommand",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenant_health_record",
    )
    probed_at = models.DateTimeField()
    latency_ms = models.PositiveIntegerField()
    healthy = models.BooleanField(default=False)
    error_message = models.CharField(max_length=_ERROR_MESSAGE_MAX_LENGTH, blank=True, default="")

    class Meta:
        ordering = ["-probed_at"]
        verbose_name_plural = "tenant health records"

    def __str__(self) -> str:
        status = "healthy" if self.healthy else "unhealthy"
        return f"{self.tenant.slug} @ {self.probed_at} ({status})"

    def clean(self) -> None:
        super().clean()
        if self.error_message:
            self.error_message = sanitize_error_message(self.error_message)

    def save(self, *args, **kwargs) -> None:
        if self.error_message:
            self.error_message = sanitize_error_message(self.error_message)
        super().save(*args, **kwargs)
