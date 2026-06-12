import re
from typing import Any

from rest_framework.exceptions import ValidationError

_FORBIDDEN_KEY_PATTERN = re.compile(r"password|secret|authkey|api_key", re.IGNORECASE)


def _collect_keys(data: Any, prefix: str = "") -> list[str]:
    if not isinstance(data, dict):
        return []
    keys: list[str] = []
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        keys.append(full_key)
        keys.extend(_collect_keys(value, full_key))
    return keys


def validate_desired_config(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("desired_config must be a JSON object.")

    forbidden = [
        key for key in _collect_keys(value) if _FORBIDDEN_KEY_PATTERN.search(key.split(".")[-1])
    ]
    if forbidden:
        joined = ", ".join(sorted(set(forbidden)))
        raise ValidationError(
            f"desired_config contains forbidden keys (password/secret/authkey/api_key): {joined}"
        )
    return value
