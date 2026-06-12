from __future__ import annotations

from typing import Any

from lifecycle.generator import generate_tenant_config
from lifecycle.scripts import generate_gateway_script, generate_linux_script
from tenants.models import Tenant


def build_provision_payload(tenant: Tenant) -> dict[str, Any]:
    config = generate_tenant_config(tenant)
    login_server = config["login_server"]
    return {
        "tenant_id": str(tenant.id),
        "tenant_slug": tenant.slug,
        "production": config["production"],
        "base_domain": config["base_domain"],
        "download_host": config["download_host"],
        "login_server": login_server,
        "headscale_host": config["headscale_host"],
        "headplane_host": config["headplane_host"],
        "db_name": config["db_name"],
        "headscale_config": config["headscale"],
        "headplane_config": config["headplane"],
        "compose_snippet": config["compose_snippet"],
        "client_scripts": {
            "linux.sh": generate_linux_script(login_server=login_server),
            "gateway.sh": generate_gateway_script(login_server=login_server),
        },
        "dns_records_json": "[]\n",
    }
