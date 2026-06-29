import uuid

from django.db import models


class DnsRecordPurpose(models.TextChoices):
    TENANT_HEADSCALE = "tenant_headscale", "Tenant headscale"
    TENANT_HEADPLANE = "tenant_headplane", "Tenant headplane"
    CONSOLE_DOWNLOAD = "console_download", "Console download"


class ManagedDnsRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fqdn = models.CharField(max_length=255, unique=True)
    record_type = models.CharField(max_length=8, default="A")
    zone_id = models.CharField(max_length=64)
    cf_record_id = models.CharField(max_length=64)
    target_ip = models.GenericIPAddressField()
    purpose = models.CharField(max_length=32, choices=DnsRecordPurpose.choices)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="managed_dns_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fqdn"]

    def __str__(self) -> str:
        return f"{self.fqdn} -> {self.target_ip}"
