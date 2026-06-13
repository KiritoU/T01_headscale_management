from __future__ import annotations

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, User
from accounts.schema_fixup import ensure_accounts_schema


class Command(BaseCommand):
    help = "Create the initial admin user from environment variables or command flags."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--username",
            default=os.environ.get("ADMIN_USERNAME", "admin"),
            help="Admin username (default: ADMIN_USERNAME env or 'admin')",
        )
        parser.add_argument(
            "--password",
            default=os.environ.get("ADMIN_PASSWORD", ""),
            help="Admin password (required via ADMIN_PASSWORD env or this flag)",
        )
        parser.add_argument(
            "--email",
            default=os.environ.get("ADMIN_EMAIL", ""),
            help="Admin email (default: ADMIN_EMAIL env or empty)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Update role and password if the user already exists",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        username = str(options["username"]).strip()
        password = str(options["password"])
        email = str(options["email"]).strip()
        force = bool(options["force"])

        if not username:
            raise CommandError("Username is required.")
        if not password:
            raise CommandError(
                "Password is required. Set ADMIN_PASSWORD or pass --password.",
            )

        if ensure_accounts_schema():
            self.stdout.write(
                self.style.WARNING(
                    "Applied missing accounts schema (legacy DB migration fixup).",
                ),
            )

        existing = User.objects.filter(username=username).first()
        if existing is not None:
            if not force:
                raise CommandError(
                    f"User '{username}' already exists. Pass --force to update.",
                )
            existing.role = Role.ADMIN
            existing.is_staff = True
            existing.is_superuser = True
            if email:
                existing.email = email
            existing.set_password(password)
            existing.save()
            self.stdout.write(self.style.SUCCESS(f"Updated admin user '{username}'."))
            return

        User.objects.create_user(
            username=username,
            password=password,
            email=email,
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.stdout.write(self.style.SUCCESS(f"Created admin user '{username}'."))
