from __future__ import annotations

import uuid

from lifecycle.identifiers import validate_suffix
from tenants.models import Tenant
from workers.models import Worker


def legacy_tenant_metadata(
    *,
    suffix: str,
    number: int,
    base_domain: str,
    production: bool = False,
) -> dict:
    """Build legacy tenant field values from generate-multi-tenants.sh naming."""
    validate_suffix(suffix)
    tenant_slug = f"{suffix}-{number}"
    db_name = f"hs_{suffix}_{number}"
    headscale_host = f"headscale-{tenant_slug}.{base_domain}"
    headplane_host = f"headplane-{tenant_slug}.{base_domain}"
    magic_dns_base = f"tailnet-{tenant_slug}.{base_domain}"

    return {
        "slug": tenant_slug,
        "db_name": db_name,
        "headscale_host": headscale_host,
        "headplane_host": headplane_host,
        "desired_config": {
            "production": production,
            "base_domain": base_domain,
            "download_host": f"download.{base_domain}",
            "dns": {
                "magic_dns_base": magic_dns_base,
            },
        },
    }


def import_legacy_tenant(
    *,
    suffix: str,
    number: int,
    base_domain: str,
    worker_id: uuid.UUID | str | None = None,
) -> Tenant:
    """Create a Tenant row from legacy provisioning metadata."""
    metadata = legacy_tenant_metadata(
        suffix=suffix,
        number=number,
        base_domain=base_domain,
    )

    worker = None
    if worker_id is not None:
        worker = Worker.objects.get(pk=worker_id)

    return Tenant.objects.create(
        slug=metadata["slug"],
        headscale_host=metadata["headscale_host"],
        headplane_host=metadata["headplane_host"],
        db_name=metadata["db_name"],
        desired_config=metadata["desired_config"],
        worker=worker,
    )
