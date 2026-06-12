from __future__ import annotations

import re

DB_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,62}")
SUFFIX_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,31}")


def validate_db_name(name: str) -> str:
    if not DB_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid database name: {name!r}")
    return name


def validate_suffix(suffix: str) -> str:
    if not SUFFIX_PATTERN.fullmatch(suffix):
        raise ValueError(f"Invalid tenant suffix: {suffix!r}")
    return suffix


def escape_sql_literal(value: str) -> str:
    return value.replace("'", "''")
