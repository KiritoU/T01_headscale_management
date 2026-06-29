from __future__ import annotations

from typing import Any

from django.conf import settings

from core.edge_settings import resolve_provision_edge_context
from lifecycle.generator import generate_tenant_config
from tenants.models import Tenant


def build_provision_payload(tenant: Tenant) -> dict[str, Any]:
    config = generate_tenant_config(tenant)
    login_server = config["login_server"]
    worker = tenant.worker
    edge = resolve_provision_edge_context(worker) if worker is not None else None
    payload: dict[str, Any] = {
        "tenant_id": str(tenant.id),
        "tenant_slug": tenant.slug,
        "production": config["production"],
        "base_domain": config["base_domain"],
        "login_server": login_server,
        "headscale_host": config["headscale_host"],
        "headplane_host": config["headplane_host"],
        "db_name": config["db_name"],
        "headscale_config": config["headscale"],
        "headplane_config": config["headplane"],
        "compose_snippet": config["compose_snippet"],
        "dns_records_json": "[]\n",
        "shared_edge_traefik": edge.shared_edge_traefik if edge else False,
    }
    if edge is not None:
        payload["acme_email"] = edge.acme_email
        payload["cf_dns_api_token"] = edge.cf_dns_api_token
    if edge and edge.shared_edge_traefik:
        payload["shared_edge_docker_network"] = settings.SHARED_EDGE_DOCKER_NETWORK
    return payload
