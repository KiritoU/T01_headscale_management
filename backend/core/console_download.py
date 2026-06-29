from __future__ import annotations

import os

from django.conf import settings

from core.edge_settings import get_platform_settings


def get_console_download_host() -> str:
    platform = get_platform_settings()
    configured = (platform.download_host or "").strip()
    if configured:
        return configured
    return getattr(settings, "DOWNLOAD_HOST", "").strip()
