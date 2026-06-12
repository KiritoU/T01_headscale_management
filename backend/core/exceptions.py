from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.responses import api_envelope


def _format_error_detail(data: Any) -> str:
    if data is None:
        return "Request failed"
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "; ".join(_format_error_detail(item) for item in data)
    if isinstance(data, dict):
        if "detail" in data and len(data) == 1:
            return _format_error_detail(data["detail"])
        parts: list[str] = []
        for field, messages in data.items():
            formatted = _format_error_detail(messages)
            if field == "detail":
                parts.append(formatted)
            else:
                parts.append(f"{field}: {formatted}")
        return "; ".join(parts) if parts else "Request failed"
    return str(data)


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    return Response(
        api_envelope(error=_format_error_detail(response.data)),
        status=response.status_code,
    )
