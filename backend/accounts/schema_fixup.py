"""Apply accounts schema on databases created before AUTH_USER_MODEL was introduced."""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone


ACCOUNTS_INITIAL = ("accounts", "0001_initial")


def accounts_tables_exist() -> bool:
    return "accounts_user" in connection.introspection.table_names()


def accounts_migration_recorded() -> bool:
    recorder = MigrationRecorder(connection)
    return recorder.migration_qs.filter(
        app=ACCOUNTS_INITIAL[0],
        name=ACCOUNTS_INITIAL[1],
    ).exists()


def ensure_accounts_schema() -> bool:
    """
    Create accounts tables and migration history when missing.

    Returns True when schema is ready, False if no fix was needed.
    """
    tables_ready = accounts_tables_exist()
    migration_ready = accounts_migration_recorded()

    if tables_ready and migration_ready:
        return False

    if not tables_ready:
        _apply_accounts_initial_migration()

    if not accounts_migration_recorded():
        _record_accounts_initial_migration()

    return True


def _apply_accounts_initial_migration() -> None:
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    migration = loader.get_migration(*ACCOUNTS_INITIAL)

    applied = [
        key
        for key in MigrationRecorder(connection).applied_migrations()
        if key != ACCOUNTS_INITIAL
    ]
    pre_state = loader.project_state(applied, at_end=True)
    post_state = pre_state.clone()
    for operation in migration.operations:
        operation.state_forwards(ACCOUNTS_INITIAL[0], post_state)

    with connection.schema_editor() as schema_editor:
        for operation in migration.operations:
            operation.database_forwards(
                ACCOUNTS_INITIAL[0],
                schema_editor,
                pre_state,
                post_state,
            )
            operation.state_forwards(ACCOUNTS_INITIAL[0], post_state)


def _record_accounts_initial_migration() -> None:
    recorder = MigrationRecorder(connection)
    admin_row = recorder.migration_qs.filter(app="admin", name="0001_initial").first()
    applied_at = (
        admin_row.applied - timedelta(seconds=1)
        if admin_row is not None
        else timezone.now()
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO django_migrations (app, name, applied)
            SELECT %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM django_migrations
                WHERE app = %s AND name = %s
            )
            """,
            [
                ACCOUNTS_INITIAL[0],
                ACCOUNTS_INITIAL[1],
                applied_at,
                ACCOUNTS_INITIAL[0],
                ACCOUNTS_INITIAL[1],
            ],
        )
