from __future__ import annotations

from django.db import models


class PlatformSettings(models.Model):
    """Singleton platform configuration (TLS edge, shared with worker provision)."""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=1,
        editable=False,
    )
    acme_email = models.EmailField(blank=True, default="")
    cf_dns_api_token = models.CharField(max_length=512, blank=True, default="")
    download_host = models.CharField(max_length=255, blank=True, default="")
    download_target_ip = models.GenericIPAddressField(null=True, blank=True)
    cf_token_verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "platform settings"
        verbose_name_plural = "platform settings"

    def __str__(self) -> str:
        return "Platform settings"

    @classmethod
    def load(cls) -> PlatformSettings:
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance
