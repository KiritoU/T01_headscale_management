import os

from django.conf import settings
from django.core.checks import Error, register

INSECURE_DEV_SECRET_KEY = "django-insecure-dev-only-change-in-production"
DEV_DB_PASSWORD = "headscale"
LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1"})


@register()
def production_env_check(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    errors = []

    secret_key = os.environ.get("DJANGO_SECRET_KEY", "").strip()
    if not secret_key:
        errors.append(
            Error(
                "DJANGO_SECRET_KEY must be set when DEBUG is False.",
                id="core.E001",
            )
        )
    elif secret_key == INSECURE_DEV_SECRET_KEY:
        errors.append(
            Error(
                "DJANGO_SECRET_KEY must not use the insecure development default in production.",
                id="core.E002",
            )
        )

    db_password = settings.DATABASES.get("default", {}).get("PASSWORD", "")
    if not db_password:
        errors.append(
            Error(
                "POSTGRES_PASSWORD must be set when DEBUG is False.",
                id="core.E003",
            )
        )
    elif db_password == DEV_DB_PASSWORD:
        errors.append(
            Error(
                "POSTGRES_PASSWORD must not use the default docker-compose password in production.",
                id="core.E004",
            )
        )

    allowed_hosts_env = os.environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
    if not allowed_hosts_env:
        errors.append(
            Error(
                "DJANGO_ALLOWED_HOSTS must be set when DEBUG is False.",
                id="core.E005",
            )
        )
    elif set(settings.ALLOWED_HOSTS) <= LOCALHOST_HOSTS:
        errors.append(
            Error(
                "DJANGO_ALLOWED_HOSTS must include production hostnames, not only localhost.",
                id="core.E006",
            )
        )

    return errors
