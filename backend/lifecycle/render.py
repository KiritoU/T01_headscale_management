from __future__ import annotations

import copy
from typing import Any

import yaml


def dict_to_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def resolve_headscale_config_for_worker(
    config: dict[str, Any],
    *,
    postgres_password: str,
) -> dict[str, Any]:
    resolved = copy.deepcopy(config)
    postgres = resolved.get("database", {}).get("postgres", {})
    if isinstance(postgres, dict):
        postgres.pop("pass_ref", None)
        postgres["pass"] = postgres_password
    return resolved


def resolve_headplane_config_for_worker(
    config: dict[str, Any],
    *,
    cookie_secret: str,
    admin_password: str,
) -> dict[str, Any]:
    resolved = copy.deepcopy(config)
    server = resolved.get("server", {})
    if isinstance(server, dict):
        server.pop("cookie_secret_ref", None)
        server["cookie_secret"] = cookie_secret

    auth = resolved.get("auth", {})
    if isinstance(auth, dict):
        local_admin = auth.get("local_admin", {})
        if isinstance(local_admin, dict):
            local_admin.pop("password_ref", None)
            local_admin["password"] = admin_password

    return resolved
