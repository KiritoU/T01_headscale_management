from __future__ import annotations

from typing import Any


def tenant_production_mode(desired_config: dict[str, Any] | None) -> bool:
    if not desired_config:
        return False
    return bool(desired_config.get("production"))


def tenant_base_domain(
    desired_config: dict[str, Any] | None,
    *,
    headscale_host: str,
) -> str:
    if desired_config:
        base_domain = desired_config.get("base_domain")
        if isinstance(base_domain, str) and base_domain:
            return base_domain

    prefix = "headscale-"
    if headscale_host.startswith(prefix) and "." in headscale_host:
        return headscale_host.split(".", 1)[1]

    return headscale_host


def tenant_download_host(
    desired_config: dict[str, Any] | None,
    *,
    base_domain: str,
) -> str:
    if desired_config:
        download_host = desired_config.get("download_host")
        if isinstance(download_host, str) and download_host:
            return download_host
    return f"download.{base_domain}"


def login_server_url(headscale_host: str, *, production: bool) -> str:
    scheme = "https" if production else "http"
    return f"{scheme}://{headscale_host}"
