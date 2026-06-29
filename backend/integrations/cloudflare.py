from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

CF_API_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_TTL = 60


class CloudflareError(Exception):
    """Raised when a Cloudflare API request fails."""


@dataclass(frozen=True)
class CloudflareTokenStatus:
    valid: bool
    status: str
    message: str


@dataclass(frozen=True)
class DnsRecordResult:
    record_id: str
    zone_id: str
    fqdn: str
    target_ip: str
    proxied: bool


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _raise_for_result(payload: dict[str, Any], *, context: str) -> None:
    if payload.get("success"):
        return
    errors = payload.get("errors") or []
    if errors:
        messages = "; ".join(
            str(item.get("message", item)) for item in errors if item is not None
        )
        raise CloudflareError(f"{context}: {messages}")
    raise CloudflareError(f"{context}: unknown Cloudflare API error")


def _format_cloudflare_errors(payload: dict[str, Any], *, context: str) -> str:
    errors = payload.get("errors") or []
    if errors:
        messages = "; ".join(
            str(item.get("message", item)) for item in errors if item is not None
        )
        return f"{context}: {messages}"
    return f"{context}: unknown Cloudflare API error"


def _cloudflare_error_codes(payload: dict[str, Any]) -> set[int]:
    codes: set[int] = set()
    for item in payload.get("errors") or []:
        if isinstance(item, dict) and item.get("code") is not None:
            try:
                codes.add(int(item["code"]))
            except (TypeError, ValueError):
                continue
    return codes


def _verify_via_zone_list(client: httpx.Client, token: str) -> CloudflareTokenStatus:
    response = client.get(
        f"{CF_API_BASE}/zones",
        headers=_headers(token.strip()),
        params={"per_page": 1},
    )
    try:
        payload = response.json()
    except ValueError:
        return CloudflareTokenStatus(
            valid=False,
            status="error",
            message="Cloudflare zone lookup returned invalid JSON.",
        )
    if response.status_code < 400 and payload.get("success"):
        zones = payload.get("result") or []
        zone_name = ""
        if zones and isinstance(zones[0], dict):
            zone_name = str(zones[0].get("name", "")).strip()
        message = "Token can access Cloudflare DNS API."
        if zone_name:
            message = f"{message} Zone access confirmed (e.g. {zone_name})."
        return CloudflareTokenStatus(
            valid=True,
            status="active",
            message=message,
        )
    return CloudflareTokenStatus(
        valid=False,
        status="invalid",
        message=_format_cloudflare_errors(payload, context="Token verification failed"),
    )


def _verify_via_token_endpoint(
    client: httpx.Client,
    token: str,
) -> CloudflareTokenStatus | None:
    response = client.get(
        f"{CF_API_BASE}/user/tokens/verify",
        headers=_headers(token.strip()),
    )
    try:
        payload = response.json()
    except ValueError:
        return CloudflareTokenStatus(
            valid=False,
            status="error",
            message="Cloudflare token verify returned invalid JSON.",
        )
    if response.status_code == 401 and 1000 in _cloudflare_error_codes(payload):
        # DNS-scoped API tokens cannot call /user/tokens/verify; fall back to zone access.
        return None
    if response.status_code >= 400 or not payload.get("success"):
        return CloudflareTokenStatus(
            valid=False,
            status="invalid",
            message=_format_cloudflare_errors(payload, context="Token verification failed"),
        )
    result = payload.get("result") or {}
    status = str(result.get("status", "unknown"))
    message = str(result.get("message", ""))
    return CloudflareTokenStatus(
        valid=status == "active",
        status=status,
        message=message,
    )


def verify_token(token: str) -> CloudflareTokenStatus:
    if not token.strip():
        return CloudflareTokenStatus(
            valid=False,
            status="missing",
            message="Cloudflare API token is not configured.",
        )
    try:
        with httpx.Client(timeout=20.0) as client:
            token_status = _verify_via_token_endpoint(client, token)
            if token_status is not None:
                return token_status
            return _verify_via_zone_list(client, token)
    except httpx.HTTPError as exc:
        return CloudflareTokenStatus(
            valid=False,
            status="error",
            message=f"Cloudflare token verification request failed: {exc}",
        )


def find_zone_id(token: str, fqdn: str) -> str:
    normalized = fqdn.strip().lower().rstrip(".")
    if not normalized:
        raise CloudflareError("FQDN is required to resolve a Cloudflare zone.")

    labels = normalized.split(".")
    candidates = [".".join(labels[index:]) for index in range(len(labels))]
    with httpx.Client(timeout=20.0) as client:
        for candidate in candidates:
            response = client.get(
                f"{CF_API_BASE}/zones",
                headers=_headers(token.strip()),
                params={"name": candidate, "status": "active"},
            )
            payload = response.json()
            if response.status_code >= 400:
                _raise_for_result(payload, context=f"Zone lookup failed for {candidate}")
            result = payload.get("result") or []
            if result:
                zone_id = str(result[0].get("id", "")).strip()
                if zone_id:
                    return zone_id
    raise CloudflareError(f"No active Cloudflare zone found for {fqdn}.")


def _record_name_for_zone(fqdn: str, zone_name: str) -> str:
    normalized_fqdn = fqdn.strip().lower().rstrip(".")
    normalized_zone = zone_name.strip().lower().rstrip(".")
    if normalized_fqdn == normalized_zone:
        return normalized_zone
    suffix = f".{normalized_zone}"
    if normalized_fqdn.endswith(suffix):
        return normalized_fqdn[: -len(suffix)]
    return normalized_fqdn


def _zone_name(token: str, zone_id: str) -> str:
    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            f"{CF_API_BASE}/zones/{zone_id}",
            headers=_headers(token.strip()),
        )
    payload = response.json()
    if response.status_code >= 400:
        _raise_for_result(payload, context="Zone detail lookup failed")
    return str((payload.get("result") or {}).get("name", "")).strip()


def upsert_a_record(
    token: str,
    *,
    fqdn: str,
    ip: str,
    proxied: bool = False,
    ttl: int = DEFAULT_TTL,
) -> DnsRecordResult:
    zone_id = find_zone_id(token, fqdn)
    zone_name = _zone_name(token, zone_id)
    record_name = _record_name_for_zone(fqdn, zone_name)
    normalized_fqdn = fqdn.strip().lower().rstrip(".")

    with httpx.Client(timeout=20.0) as client:
        list_response = client.get(
            f"{CF_API_BASE}/zones/{zone_id}/dns_records",
            headers=_headers(token.strip()),
            params={"type": "A", "name": normalized_fqdn},
        )
        list_payload = list_response.json()
        if list_response.status_code >= 400:
            _raise_for_result(list_payload, context=f"DNS record lookup failed for {fqdn}")

        body = {
            "type": "A",
            "name": record_name,
            "content": ip,
            "ttl": ttl,
            "proxied": proxied,
        }
        existing = list_payload.get("result") or []
        if existing:
            record_id = str(existing[0].get("id", "")).strip()
            response = client.patch(
                f"{CF_API_BASE}/zones/{zone_id}/dns_records/{record_id}",
                headers=_headers(token.strip()),
                json=body,
            )
        else:
            response = client.post(
                f"{CF_API_BASE}/zones/{zone_id}/dns_records",
                headers=_headers(token.strip()),
                json=body,
            )
        payload = response.json()
        if response.status_code >= 400:
            _raise_for_result(payload, context=f"DNS record upsert failed for {fqdn}")

    result = payload.get("result") or {}
    record_id = str(result.get("id", "")).strip()
    if not record_id:
        raise CloudflareError(f"DNS record upsert for {fqdn} returned no record id.")
    return DnsRecordResult(
        record_id=record_id,
        zone_id=zone_id,
        fqdn=normalized_fqdn,
        target_ip=ip,
        proxied=proxied,
    )


def delete_a_record(token: str, *, zone_id: str, record_id: str) -> None:
    with httpx.Client(timeout=20.0) as client:
        response = client.delete(
            f"{CF_API_BASE}/zones/{zone_id}/dns_records/{record_id}",
            headers=_headers(token.strip()),
        )
    if response.status_code == 404:
        return
    payload = response.json()
    if response.status_code >= 400:
        _raise_for_result(payload, context="DNS record delete failed")
