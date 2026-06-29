from __future__ import annotations

from rest_framework.request import Request


def get_client_ip(request: Request) -> str | None:
    """Return the client IP, preferring the first X-Forwarded-For hop."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    remote_addr = request.META.get("REMOTE_ADDR")
    if isinstance(remote_addr, str) and remote_addr.strip():
        return remote_addr.strip()
    return None
