from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from agents.models import AgentCommand, CommandState
from tenants.bootstrap_secrets import resolve_bootstrap_secrets
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Backfill tenant bootstrap_secrets from ack payloads or worker secrets files."

    def handle(self, *args, **options) -> None:
        updated = 0
        for tenant in Tenant.objects.order_by("slug"):
            command = (
                AgentCommand.objects.filter(
                    command="bootstrap_tenant",
                    payload__tenant_id=str(tenant.id),
                    state=CommandState.ACKED,
                )
                .order_by("-acked_at")
                .first()
            )
            bootstrap = dict((command.result or {}).get("bootstrap") or {}) if command else {}
            before = dict(tenant.bootstrap_secrets or {})
            secrets = resolve_bootstrap_secrets(tenant, bootstrap, persist=True)
            tenant.refresh_from_db()
            after = dict(tenant.bootstrap_secrets or {})
            if after and after != before:
                updated += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{tenant.slug}: synced {', '.join(sorted(after.keys()))}",
                    ),
                )
            elif secrets:
                self.stdout.write(f"{tenant.slug}: already up to date")
            else:
                self.stdout.write(
                    self.style.WARNING(f"{tenant.slug}: no bootstrap secrets found"),
                )

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} tenant(s)."))
