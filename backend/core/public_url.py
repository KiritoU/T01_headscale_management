from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.http import HttpRequest


def get_public_base_url(request: HttpRequest | None = None) -> str:
    configured = getattr(settings, "PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    if request is None:
        return ""
    return request.build_absolute_uri("/").rstrip("/")


def build_agent_install_curl(
    request: HttpRequest,
    *,
    script_name: str,
    token: str,
) -> str:
    base = get_public_base_url(request)
    if not base:
        msg = "PUBLIC_BASE_URL is not configured and request origin is unavailable"
        raise ValueError(msg)
    quoted_token = quote(token, safe="")
    return f'curl -fsSL "{base}/{script_name}?token={quoted_token}" | bash'
