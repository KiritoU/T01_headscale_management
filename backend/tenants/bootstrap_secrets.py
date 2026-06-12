from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings

from tenants.models import Tenant

_BOOTSTRAP_SECRET_KEYS = (
    "api_key",
    "auth_key_gateway",
    "auth_key_workspace",
    "admin_user_id",
)

_ENV_KEY_MAP = {
    "API_KEY": "api_key",
    "AUTH_KEY_GATEWAY": "auth_key_gateway",
    "AUTH_KEY_WORKSPACE": "auth_key_workspace",
    "ADMIN_USER_ID": "admin_user_id",
}


def worker_stack_dir() -> Path:
    configured = getattr(settings, "WORKER_STACK_DIR", "/opt/headscale-worker-stack")
    return Path(configured)


def default_secrets_path(tenant_slug: str) -> Path:
    return worker_stack_dir() / "tenants" / tenant_slug / "bootstrap-secrets.env"


def read_bootstrap_secrets_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    secrets: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, _, value = line.partition("=")
        mapped = _ENV_KEY_MAP.get(env_key.strip())
        if mapped and value.strip():
            secrets[mapped] = value.strip()
    return secrets


def extract_bootstrap_secrets(bootstrap: dict[str, Any] | None) -> dict[str, str]:
    if not bootstrap:
        return {}
    secrets: dict[str, str] = {}
    for key in _BOOTSTRAP_SECRET_KEYS:
        value = bootstrap.get(key)
        if value is not None and str(value).strip():
            secrets[key] = str(value).strip()
    return secrets


def resolve_bootstrap_secrets(
    tenant: Tenant,
    bootstrap: dict[str, Any] | None = None,
    *,
    stored: dict[str, str] | None = None,
    persist: bool = False,
) -> dict[str, str]:
    current = dict(stored if stored is not None else (tenant.bootstrap_secrets or {}))
    if current.get("api_key"):
        return current

    from_ack = extract_bootstrap_secrets(bootstrap)
    if from_ack.get("api_key"):
        merged = {**current, **from_ack}
        if persist:
            Tenant.objects.filter(pk=tenant.pk).update(bootstrap_secrets=merged)
        return merged

    candidate_paths: list[Path] = []
    secrets_path = (bootstrap or {}).get("secrets_path")
    if isinstance(secrets_path, str) and secrets_path.strip():
        candidate_paths.append(Path(secrets_path.strip()))
    candidate_paths.append(default_secrets_path(tenant.slug))

    from_file: dict[str, str] = {}
    seen: set[Path] = set()
    for path in candidate_paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        from_file = read_bootstrap_secrets_env(resolved)
        if from_file:
            break

    merged = {**from_file, **current, **from_ack}
    if merged.get("api_key"):
        if persist:
            Tenant.objects.filter(pk=tenant.pk).update(bootstrap_secrets=merged)
        return merged

    return merged

