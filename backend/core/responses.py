from typing import Any


def api_envelope(
    *,
    data: Any = None,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "meta": meta or {},
    }
