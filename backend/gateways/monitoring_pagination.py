from __future__ import annotations

import math
from typing import Any

from django.db.models import QuerySet
from rest_framework.request import Request

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 25
MAX_LIMIT = 200


def parse_pagination_params(request: Request) -> tuple[int, int]:
    try:
        page = int(request.query_params.get("page", DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE
    try:
        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    page = max(page, DEFAULT_PAGE)
    limit = min(max(limit, 1), MAX_LIMIT)
    return page, limit


def paginate_queryset(
    queryset: QuerySet[Any],
    *,
    page: int,
    limit: int,
) -> tuple[list[Any], dict[str, int]]:
    total = queryset.count()
    pages = max(1, math.ceil(total / limit)) if total else 1
    current_page = min(page, pages) if total else DEFAULT_PAGE
    offset = (current_page - 1) * limit
    items = list(queryset[offset : offset + limit])
    meta = {
        "total": total,
        "page": current_page,
        "limit": limit,
        "pages": pages,
    }
    return items, meta


def filter_hosts_queryset(queryset: QuerySet[Any], request: Request) -> QuerySet[Any]:
    ip = str(request.query_params.get("ip", "")).strip()
    if ip:
        queryset = queryset.filter(ip__contains=ip)

    is_new = str(request.query_params.get("is_new", "")).strip().lower()
    if is_new == "true":
        queryset = queryset.filter(is_new=True)
    elif is_new == "false":
        queryset = queryset.filter(is_new=False)

    vuln_pending = str(request.query_params.get("vuln_scan_pending", "")).strip().lower()
    if vuln_pending == "true":
        queryset = queryset.filter(vuln_scan_pending=True)
    elif vuln_pending == "false":
        queryset = queryset.filter(vuln_scan_pending=False)

    return queryset


def filter_alerts_queryset(queryset: QuerySet[Any], request: Request) -> QuerySet[Any]:
    host_ip = str(request.query_params.get("host_ip", "")).strip()
    if host_ip:
        queryset = queryset.filter(host_ip__contains=host_ip)

    alert_type = str(request.query_params.get("alert_type", "")).strip()
    if alert_type:
        queryset = queryset.filter(alert_type=alert_type)

    return queryset


def filter_findings_queryset(queryset: QuerySet[Any], request: Request) -> QuerySet[Any]:
    host_ip = str(request.query_params.get("host_ip", "")).strip()
    if host_ip:
        queryset = queryset.filter(discovered_host__ip__contains=host_ip)

    severity = str(request.query_params.get("severity", "")).strip().lower()
    if severity:
        queryset = queryset.filter(severity=severity)

    source = str(request.query_params.get("source", "")).strip()
    if source:
        queryset = queryset.filter(source__icontains=source)

    return queryset
