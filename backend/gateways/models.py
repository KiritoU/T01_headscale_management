import uuid

from django.db import models

from gateways.monitoring_policy import (
    SCAN_STRATEGY_FULL,
    SCAN_STRATEGY_ROTATING,
    default_monitored_cidrs,
    policy_config_from_model,
    validate_discover_interval,
    validate_monitored_cidrs,
)


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


class ScanStrategy(models.TextChoices):
    ROTATING = SCAN_STRATEGY_ROTATING, "Rotating chunks"
    FULL = SCAN_STRATEGY_FULL, "Full sweep"


class GatewayMonitorPolicy(models.Model):
    """Per-gateway monitoring configuration (scan schedule, CIDR targets, vuln options)."""

    gateway = models.OneToOneField(
        Gateway,
        on_delete=models.CASCADE,
        related_name="monitor_policy",
    )
    enabled = models.BooleanField(default=False)
    monitored_cidrs = models.JSONField(default=default_monitored_cidrs)
    scan_strategy = models.CharField(
        max_length=16,
        choices=ScanStrategy.choices,
        default=ScanStrategy.ROTATING,
    )
    chunk_count = models.PositiveIntegerField(default=4)
    discover_interval_minutes = models.PositiveIntegerField(default=60)
    vuln_rescan_days = models.PositiveIntegerField(default=1)
    vuln_scan_enabled = models.BooleanField(default=False)
    vuln_modules = models.JSONField(default=list, blank=True)
    nuclei_enabled = models.BooleanField(default=True)
    vuln_parallel_workers = models.PositiveIntegerField(default=4)
    chunk_cursor = models.PositiveIntegerField(default=0)
    last_scheduled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Gateway Monitor Policy"
        verbose_name_plural = "Gateway Monitor Policies"

    def __str__(self) -> str:
        return f"policy:{self.gateway}"

    def clean(self) -> None:
        validate_monitored_cidrs(self.monitored_cidrs)
        config = policy_config_from_model(self)
        validate_discover_interval(config, self.discover_interval_minutes)


class ScanSnapshot(models.Model):
    """Result snapshot produced after each monitor scan chunk."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gateway = models.ForeignKey(
        Gateway,
        on_delete=models.CASCADE,
        related_name="scan_snapshots",
    )
    command = models.ForeignKey(
        "agents.AgentCommand",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scan_snapshots",
    )
    scanned_at = models.DateTimeField()
    chunk_cidrs = models.JSONField(default=list)
    host_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-scanned_at"]

    def __str__(self) -> str:
        return f"snapshot:{self.gateway_id}@{self.scanned_at}"


class DiscoveredHost(models.Model):
    """Network host found during a gateway monitor scan."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gateway = models.ForeignKey(
        Gateway,
        on_delete=models.CASCADE,
        related_name="discovered_hosts",
    )
    ip = models.GenericIPAddressField(db_index=True)
    hostname = models.CharField(max_length=255, blank=True)
    mac = models.CharField(max_length=17, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    is_new = models.BooleanField(default=True)
    vuln_scan_pending = models.BooleanField(default=False)
    last_vuln_scan_at = models.DateTimeField(null=True, blank=True)
    open_ports = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["ip"]
        constraints = [
            models.UniqueConstraint(
                fields=["gateway", "ip"], name="unique_gateway_host_ip"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.gateway_id}:{self.ip}"


class Severity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"
    INFO = "info", "Info"


class VulnFinding(models.Model):
    """Vulnerability or finding associated with a discovered host."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    discovered_host = models.ForeignKey(
        DiscoveredHost,
        on_delete=models.CASCADE,
        related_name="vuln_findings",
    )
    source = models.CharField(max_length=64)
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.INFO,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    finding_id = models.CharField(max_length=128, blank=True, db_index=True)
    details = models.JSONField(default=dict, blank=True)
    found_at = models.DateTimeField()

    class Meta:
        ordering = ["-found_at", "severity"]

    def __str__(self) -> str:
        return f"{self.severity}:{self.title}"


class AlertType(models.TextChoices):
    NEW_HOST = "new_host", "New Host"


class MonitorAlert(models.Model):
    """Alert raised by the monitoring scheduler for a gateway event."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gateway = models.ForeignKey(
        Gateway,
        on_delete=models.CASCADE,
        related_name="monitor_alerts",
    )
    alert_type = models.CharField(
        max_length=32,
        choices=AlertType.choices,
        default=AlertType.NEW_HOST,
        db_index=True,
    )
    host_ip = models.GenericIPAddressField()
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.alert_type}:{self.host_ip}"
