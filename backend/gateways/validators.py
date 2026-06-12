from __future__ import annotations

import ipaddress


def validate_cidr_list(routes: list[str]) -> list[str]:
    """Validate a list of CIDR strings; return normalized network strings."""
    if not routes:
        msg = "At least one route is required"
        raise ValueError(msg)

    validated: list[str] = []
    for route in routes:
        text = str(route).strip()
        if not text:
            msg = "Empty CIDR route is not allowed"
            raise ValueError(msg)
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as exc:
            msg = f"Invalid CIDR: {route}"
            raise ValueError(msg) from exc
        validated.append(str(network))
    return validated
