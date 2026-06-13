import pytest

from accounts.schema_fixup import (
    accounts_migration_recorded,
    accounts_tables_exist,
    ensure_accounts_schema,
)


@pytest.mark.django_db
def test_ensure_accounts_schema_is_idempotent():
    assert accounts_tables_exist()
    assert accounts_migration_recorded()

    changed = ensure_accounts_schema()
    assert changed is False
