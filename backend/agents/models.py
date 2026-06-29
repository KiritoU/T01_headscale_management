import uuid

from django.db import models


class AgentType(models.TextChoices):
    WORKER = "worker", "Worker"
    GATEWAY = "gateway", "Gateway"


class Agent(models.Model):
    """Polling identity shared by worker and gateway agents."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_type = models.CharField(max_length=16, choices=AgentType.choices)
    token_prefix = models.CharField(max_length=8, db_index=True)
    token_hash = models.CharField(max_length=64)
    poll_interval_seconds = models.IntegerField(default=15)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    tenant_inventory = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.agent_type}:{self.id}"


class CommandState(models.TextChoices):
    PENDING = "pending", "Pending"
    DISPATCHED = "dispatched", "Dispatched"
    ACKED = "acked", "Acked"
    FAILED = "failed", "Failed"


class AgentCommand(models.Model):
    """Command queued for an agent; delivered on poll."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="commands")
    command = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    state = models.CharField(
        max_length=16,
        choices=CommandState.choices,
        default=CommandState.PENDING,
        db_index=True,
    )
    dispatched_at = models.DateTimeField(null=True, blank=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["agent", "state", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.command}:{self.state}"


class AgentModule(models.Model):
    """Module installed on an agent, reported via heartbeat."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="modules")
    name = models.CharField(max_length=64)
    installed_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["agent", "name"], name="unique_agent_module"),
        ]

    def __str__(self) -> str:
        return f"{self.agent_id}:{self.name}"


class ResourceSample(models.Model):
    """Point-in-time host resource metrics reported via agent heartbeat."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        related_name="resource_samples",
    )
    sampled_at = models.DateTimeField(db_index=True)
    cpu_percent = models.FloatField(null=True, blank=True)
    mem_percent = models.FloatField(null=True, blank=True)
    disk_percent = models.FloatField(null=True, blank=True)
    mem_total_bytes = models.BigIntegerField(null=True, blank=True)
    mem_used_bytes = models.BigIntegerField(null=True, blank=True)
    disk_total_bytes = models.BigIntegerField(null=True, blank=True)
    disk_used_bytes = models.BigIntegerField(null=True, blank=True)
    net_rx_bytes_per_sec = models.BigIntegerField(null=True, blank=True)
    net_tx_bytes_per_sec = models.BigIntegerField(null=True, blank=True)
    load_avg_1m = models.FloatField(null=True, blank=True)
    cpu_count = models.PositiveIntegerField(null=True, blank=True)
    uptime_seconds = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sampled_at"]
        indexes = [
            models.Index(fields=["agent", "sampled_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.agent_id}@{self.sampled_at}"
