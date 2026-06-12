from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lifecycle.deployment import (
    login_server_url,
    tenant_base_domain,
    tenant_download_host,
    tenant_production_mode,
)
from lifecycle.stack_generator import traefik_router_labels
from tenants.models import Tenant

DEFAULT_POSTGRES_USER = "headscale"
DEFAULT_POSTGRES_PASSWORD_REF = "env:POSTGRES_PASSWORD"


@dataclass(frozen=True)
class TenantConfigInput:
    slug: str
    headscale_host: str
    headplane_host: str
    db_name: str
    magic_dns_base: str
    login_server: str
    headscale_container: str
    headplane_container: str
    production: bool
    base_domain: str
    download_host: str


def _derive_magic_dns_base(
    *,
    slug: str,
    headscale_host: str,
    desired_config: dict[str, Any],
) -> str:
    dns_config = desired_config.get("dns", {})
    if isinstance(dns_config, dict):
        magic_dns_base = dns_config.get("magic_dns_base")
        if isinstance(magic_dns_base, str) and magic_dns_base:
            return magic_dns_base

    prefix = f"headscale-{slug}."
    if headscale_host.startswith(prefix):
        base_domain = headscale_host[len(prefix) :]
        return f"tailnet-{slug}.{base_domain}"

    return f"tailnet-{slug}"


def tenant_config_input_from_model(tenant: Tenant) -> TenantConfigInput:
    desired_config = dict(tenant.desired_config or {})
    production = tenant_production_mode(desired_config)
    base_domain = tenant_base_domain(
        desired_config,
        headscale_host=tenant.headscale_host,
    )
    magic_dns_base = _derive_magic_dns_base(
        slug=tenant.slug,
        headscale_host=tenant.headscale_host,
        desired_config=desired_config,
    )
    return TenantConfigInput(
        slug=tenant.slug,
        headscale_host=tenant.headscale_host,
        headplane_host=tenant.headplane_host,
        db_name=tenant.db_name,
        magic_dns_base=magic_dns_base,
        login_server=login_server_url(tenant.headscale_host, production=production),
        headscale_container=f"headscale-{tenant.slug}",
        headplane_container=f"headplane-{tenant.slug}",
        production=production,
        base_domain=base_domain,
        download_host=tenant_download_host(desired_config, base_domain=base_domain),
    )


def generate_headscale_config(config_input: TenantConfigInput) -> dict[str, Any]:
    return {
        "server_url": config_input.login_server,
        "listen_addr": "0.0.0.0:8080",
        "database": {
            "type": "postgres",
            "debug": False,
            "gorm": {
                "prepare_stmt": False,
                "parameterized_queries": True,
                "skip_err_record_not_found": True,
                "slow_threshold": 1000,
            },
            "postgres": {
                "host": "pgbouncer",
                "port": 6432,
                "name": config_input.db_name,
                "user": DEFAULT_POSTGRES_USER,
                "pass_ref": DEFAULT_POSTGRES_PASSWORD_REF,
                "max_open_conns": 5,
                "max_idle_conns": 5,
                "conn_max_idle_time_secs": 3600,
                "ssl": False,
            },
        },
        "prefixes": {
            "v4": "100.64.0.0/10",
            "v6": "fd7a:115c:a1e0::/48",
            "allocation": "sequential",
        },
        "private_key_path": "/var/lib/headscale/private.key",
        "noise": {"private_key_path": "/var/lib/headscale/noise_private.key"},
        "log": {"level": "info"},
        "policy": {"mode": "database"},
        "dns": {
            "magic_dns": True,
            "base_domain": config_input.magic_dns_base,
            "override_local_dns": True,
            "nameservers": {"global": ["1.1.1.1", "8.8.8.8"]},
            "extra_records_path": "/etc/headscale/dns_records.json",
        },
        "derp": {
            "server": {"enabled": False},
            "auto_update_enabled": True,
            "urls": ["https://controlplane.tailscale.com/derpmap/default"],
        },
        "unix_socket": "/var/run/headscale/headscale.sock",
    }


def generate_headplane_config(config_input: TenantConfigInput) -> dict[str, Any]:
    slug = config_input.slug
    return {
        "server": {
            "host": "0.0.0.0",
            "port": 3000,
            "cookie_secret_ref": f"secrets://tenants/{slug}/headplane/cookie_secret",
            "cookie_secure": config_input.production,
        },
        "headscale": {
            "url": f"http://{config_input.headscale_container}:8080",
            "public_url": config_input.login_server,
            "config_path": "/etc/headscale/config.yaml",
            "dns_records_path": "/etc/headscale/dns_records.json",
            "config_strict": True,
        },
        "integration": {
            "docker": {
                "enabled": True,
                "container_name": config_input.headscale_container,
                "socket": "unix:///var/run/docker.sock",
            },
        },
        "auth": {
            "local_admin": {
                "enabled": True,
                "username": "admin",
                "password_ref": f"secrets://tenants/{slug}/headplane/admin_password",
            },
        },
        "ui": {
            "tailnet_name": "My Tailnet",
            "base_domain": config_input.magic_dns_base,
        },
    }


def generate_compose_snippet(config_input: TenantConfigInput) -> str:
    slug = config_input.slug
    hs = config_input.headscale_container
    hp = config_input.headplane_container
    hs_host = config_input.headscale_host
    hp_host = config_input.headplane_host
    production = config_input.production

    hs_labels = traefik_router_labels(
        router_name=hs,
        host=hs_host,
        production=production,
        service_port=8080,
        middlewares=(f"cors-{hs}",),
    )
    cors_origin = (
        f"https://{hp_host}" if production else f"http://{hp_host}"
    )
    hs_label_lines = "\n".join(f'      - "{label}"' for label in hs_labels)
    hs_label_lines += (
        f'\n      - "me.tale.headplane.target={hs}"'
        f'\n      - "traefik.http.middlewares.cors-{hs}.headers.accesscontrolallowheaders=*"'
        f'\n      - "traefik.http.middlewares.cors-{hs}.headers.accesscontrolallowmethods=GET,POST,PUT"'
        f'\n      - "traefik.http.middlewares.cors-{hs}.headers.accesscontrolalloworiginlist={cors_origin}"'
    )

    hp_labels = traefik_router_labels(
        router_name=hp,
        host=hp_host,
        production=production,
        service_port=3000,
    )
    hp_label_lines = "\n".join(f'      - "{label}"' for label in hp_labels)

    return f"""  {hs}:
    image: headscale/headscale:latest
    container_name: {hs}
    command: serve
    restart: unless-stopped
    depends_on:
      pgbouncer:
        condition: service_started
    volumes:
      - ./tenants/{slug}/headscale/config.yaml:/etc/headscale/config.yaml
      - ./tenants/{slug}/headscale/dns_records.json:/etc/headscale/dns_records.json
      - ./tenants/{slug}/headscale/data:/var/lib/headscale
      - ./ACL.json:/etc/headscale/ACL.json:ro
    labels:
{hs_label_lines}

  {hp}:
    image: ghcr.io/tale/headplane:latest
    container_name: {hp}
    restart: unless-stopped
    depends_on:
      - {hs}
    volumes:
      - ./tenants/{slug}/headplane/config.yaml:/etc/headplane/config.yaml
      - ./tenants/{slug}/headplane/data:/var/lib/headplane
      - ./tenants/{slug}/headscale/config.yaml:/etc/headscale/config.yaml
      - ./tenants/{slug}/headscale/dns_records.json:/etc/headscale/dns_records.json
      - /var/run/docker.sock:/var/run/docker.sock:ro
    labels:
{hp_label_lines}
"""


def generate_tenant_config(tenant: Tenant) -> dict[str, Any]:
    config_input = tenant_config_input_from_model(tenant)
    return {
        "slug": config_input.slug,
        "login_server": config_input.login_server,
        "headscale_host": config_input.headscale_host,
        "headplane_host": config_input.headplane_host,
        "db_name": config_input.db_name,
        "magic_dns_base": config_input.magic_dns_base,
        "production": config_input.production,
        "base_domain": config_input.base_domain,
        "download_host": config_input.download_host,
        "headscale": generate_headscale_config(config_input),
        "headplane": generate_headplane_config(config_input),
        "compose_snippet": generate_compose_snippet(config_input),
    }
