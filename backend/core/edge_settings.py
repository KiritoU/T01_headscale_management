from __future__ import annotations

import os
from dataclasses import dataclass

from core.models import PlatformSettings
from workers.models import Worker


@dataclass(frozen=True)
class ProvisionEdgeContext:
    shared_edge_traefik: bool
    acme_email: str
    cf_dns_api_token: str


def get_platform_settings() -> PlatformSettings:
    return PlatformSettings.load()


def resolve_provision_edge_context(worker: Worker) -> ProvisionEdgeContext:
    settings = get_platform_settings()
    acme_email = (settings.acme_email or "").strip()
    token = (settings.cf_dns_api_token or "").strip()

    if not acme_email:
        acme_email = os.environ.get("ACME_EMAIL", "").strip()
    if not token:
        token = os.environ.get("CF_DNS_API_TOKEN", "").strip() or os.environ.get(
            "CLOUDFLARE_DNS_API_TOKEN",
            "",
        ).strip()

    return ProvisionEdgeContext(
        shared_edge_traefik=worker.shared_edge_traefik,
        acme_email=acme_email,
        cf_dns_api_token=token,
    )


def validate_production_edge_config(worker: Worker, *, production: bool) -> None:
    if not production:
        return

    context = resolve_provision_edge_context(worker)
    if context.shared_edge_traefik:
        return

    missing: list[str] = []
    if not context.acme_email:
        missing.append("ACME email")
    if not context.cf_dns_api_token:
        missing.append("Cloudflare DNS API token")
    if missing:
        msg = (
            "Production tenants require platform edge settings: "
            + ", ".join(missing)
            + ". Configure them under Edge & TLS settings."
        )
        raise ValueError(msg)
