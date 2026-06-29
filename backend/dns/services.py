from __future__ import annotations

import os
from dataclasses import dataclass

from django.utils import timezone

from core.edge_settings import get_platform_settings
from core.models import PlatformSettings
from dns.models import DnsRecordPurpose, ManagedDnsRecord
from integrations.cloudflare import CloudflareError, delete_a_record, upsert_a_record
from lifecycle.deployment import tenant_production_mode
from tenants.models import Tenant
from workers.models import Worker


class DnsConfigurationError(Exception):
    """Raised when DNS automation cannot complete."""


@dataclass(frozen=True)
class DownloadDnsStatus:
    fqdn: str
    target_ip: str
    synced: bool
    cf_record_id: str | None


@dataclass(frozen=True)
class PlatformCfTokenResolution:
    token: str
    source: str


def resolve_platform_cf_token_resolution() -> PlatformCfTokenResolution:
    settings_row = get_platform_settings()
    token = (settings_row.cf_dns_api_token or "").strip()
    if token:
        return PlatformCfTokenResolution(token=token, source="database")
    env_token = (
        os.environ.get("CF_DNS_API_TOKEN", "").strip()
        or os.environ.get("CLOUDFLARE_DNS_API_TOKEN", "").strip()
    )
    if env_token:
        return PlatformCfTokenResolution(token=env_token, source="environment")
    return PlatformCfTokenResolution(token="", source="none")


def resolve_platform_cf_token() -> str:
    return resolve_platform_cf_token_resolution().token


def worker_effective_public_ip(worker: Worker) -> str:
    override = (worker.public_ip_override or "").strip()
    if override:
        return override
    detected = (worker.public_ip or "").strip()
    if detected:
        return detected
    msg = (
        "Worker public IP is not known yet. Wait for the worker agent heartbeat "
        "or set a manual public IP override on the worker."
    )
    raise DnsConfigurationError(msg)


def _persist_managed_record(
    *,
    result_fqdn: str,
    zone_id: str,
    record_id: str,
    target_ip: str,
    purpose: str,
    tenant: Tenant | None,
) -> ManagedDnsRecord:
    record, _ = ManagedDnsRecord.objects.update_or_create(
        fqdn=result_fqdn,
        defaults={
            "record_type": "A",
            "zone_id": zone_id,
            "cf_record_id": record_id,
            "target_ip": target_ip,
            "purpose": purpose,
            "tenant": tenant,
        },
    )
    return record


def _upsert_managed_a_record(
    *,
    token: str,
    fqdn: str,
    target_ip: str,
    purpose: str,
    tenant: Tenant | None,
) -> ManagedDnsRecord:
    try:
        result = upsert_a_record(token, fqdn=fqdn, ip=target_ip, proxied=False)
    except CloudflareError as exc:
        raise DnsConfigurationError(str(exc)) from exc
    return _persist_managed_record(
        result_fqdn=result.fqdn,
        zone_id=result.zone_id,
        record_id=result.record_id,
        target_ip=result.target_ip,
        purpose=purpose,
        tenant=tenant,
    )


def ensure_tenant_dns(tenant: Tenant) -> list[ManagedDnsRecord]:
    if not tenant_production_mode(tenant.desired_config):
        return []
    worker = tenant.worker
    if worker is None:
        raise DnsConfigurationError("Tenant has no assigned worker.")

    token = resolve_platform_cf_token()
    if not token:
        raise DnsConfigurationError(
            "Production tenants require a Cloudflare DNS API token. "
            "Configure it under Console settings.",
        )

    target_ip = worker_effective_public_ip(worker)
    records: list[ManagedDnsRecord] = []
    for fqdn, purpose in (
        (tenant.headscale_host, DnsRecordPurpose.TENANT_HEADSCALE),
        (tenant.headplane_host, DnsRecordPurpose.TENANT_HEADPLANE),
    ):
        records.append(
            _upsert_managed_a_record(
                token=token,
                fqdn=fqdn,
                target_ip=target_ip,
                purpose=purpose,
                tenant=tenant,
            ),
        )
    return records


def remove_tenant_dns(tenant: Tenant) -> None:
    token = resolve_platform_cf_token()
    records = list(ManagedDnsRecord.objects.filter(tenant=tenant))
    for record in records:
        if token:
            try:
                delete_a_record(
                    token,
                    zone_id=record.zone_id,
                    record_id=record.cf_record_id,
                )
            except CloudflareError:
                pass
        record.delete()


def ensure_download_dns(settings_row: PlatformSettings | None = None) -> ManagedDnsRecord:
    platform = settings_row or get_platform_settings()
    download_host = (platform.download_host or "").strip()
    target_ip = (platform.download_target_ip or "").strip()
    if not download_host:
        raise DnsConfigurationError("Download host is not configured.")
    if not target_ip:
        raise DnsConfigurationError("Download target IP is not configured.")

    token = resolve_platform_cf_token()
    if not token:
        raise DnsConfigurationError(
            "Cloudflare DNS API token is required to manage the download host record.",
        )

    record = _upsert_managed_a_record(
        token=token,
        fqdn=download_host,
        target_ip=target_ip,
        purpose=DnsRecordPurpose.CONSOLE_DOWNLOAD,
        tenant=None,
    )
    platform.cf_token_verified_at = timezone.now()
    platform.save(update_fields=["cf_token_verified_at", "updated_at"])
    return record


def download_dns_status() -> DownloadDnsStatus | None:
    platform = get_platform_settings()
    download_host = (platform.download_host or "").strip()
    target_ip = (platform.download_target_ip or "").strip()
    if not download_host or not target_ip:
        return None
    managed = ManagedDnsRecord.objects.filter(
        fqdn=download_host.lower().rstrip("."),
        purpose=DnsRecordPurpose.CONSOLE_DOWNLOAD,
    ).first()
    return DownloadDnsStatus(
        fqdn=download_host,
        target_ip=target_ip,
        synced=managed is not None and managed.target_ip == target_ip,
        cf_record_id=managed.cf_record_id if managed else None,
    )
